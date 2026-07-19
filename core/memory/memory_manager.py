"""
memory_manager.py

Orchestrates the Redis ↔ MongoDB ↔ GraphMemory shift logic.

Rules:
  - Active chat lives in Redis (fast, TTL-based)
  - When a new chat starts: current Redis session → summarize → archive to MongoDB
    → extract knowledge → ingest into GraphMemory
  - When an old chat is resumed: load from MongoDB → push to Redis
  - Cross-session reference detected: search GraphMemory → inject matched session
    context into current prompt as additional context

This is the only module that touches Redis, MongoDB, and GraphMemory.
Everything else talks to MemoryManager, not the stores directly.
"""

from __future__ import annotations

from core.claude_runner import ClaudeRunnerError, run
from core.memory.graph_extractor import detect_cross_session_reference, extract_session_knowledge
from core.memory.graph_memory import GraphMemory, SessionMatch
from core.memory.mongo_memory import MongoMemory
from core.memory.redis_memory import RedisMemory


_SUMMARIZE_SYSTEM = """You are a conversation summarizer for a SQL assistant.
Summarize the conversation so a future session can quickly understand:
- What databases/tables were explored
- What questions were asked and answered
- Any important findings or patterns discovered
- Any unresolved questions

Keep the summary under 200 words. Be specific about table names and metrics mentioned."""


class MemoryManager:
    """
    Single interface for all conversation memory operations.

    Usage:
        mm = MemoryManager()
        mm.start_chat(chat_id)
        mm.add_message(chat_id, role="user", content="...")
        mm.add_message(chat_id, role="assistant", content="...", metadata={...})
        mm.close_chat(chat_id)   # archives to MongoDB
        mm.resume_chat(chat_id)  # loads from MongoDB → Redis
    """

    def __init__(
        self,
        redis: RedisMemory | None = None,
        mongo: MongoMemory | None = None,
        graph: GraphMemory | None = None,
    ) -> None:
        self._redis = redis or RedisMemory()
        self._mongo = mongo or MongoMemory()
        self._graph = graph  # injected at startup; None = graph disabled

    # ------------------------------------------------------------------
    # Chat lifecycle
    # ------------------------------------------------------------------

    def start_chat(self, chat_id: str, db_alias: str = "") -> None:
        """
        Begin a new chat session.
        Archives any existing active session first (shouldn't happen, but safe).
        """
        self._mongo.create_chat(chat_id, db_alias=db_alias)

    def close_chat(self, chat_id: str) -> None:
        """
        Archive the active Redis session to MongoDB and ingest into GraphMemory.

        Steps:
          1. Pull messages from Redis
          2. Claude summarizes the session → MongoDB
          3. Messages persisted to MongoDB
          4. Redis cleared
          5. Extract knowledge from messages → GraphMemory (non-blocking on failure)
        """
        messages = self._redis.get_messages(chat_id)
        if not messages:
            return

        summary = self._summarize(messages)
        self._mongo.archive_summary(chat_id, summary)

        for msg in messages:
            self._mongo.append_message(chat_id, msg)

        self._redis.clear_chat(chat_id)

        # Ingest into knowledge graph — failure must never block chat archival
        if self._graph is not None:
            try:
                knowledge = extract_session_knowledge(messages)
                db_alias = self._mongo.get_db_alias(chat_id)
                self._graph.ingest_session(chat_id, knowledge, db_alias=db_alias)
            except Exception:
                pass  # graph ingestion is best-effort

    def resume_chat(self, chat_id: str) -> dict:
        """
        Load an archived chat from MongoDB back into Redis.

        Returns a context dict with summary + last messages so the
        API layer can restore the conversation state.
        """
        summary = self._mongo.get_chat_summary(chat_id)
        last_messages = self._mongo.get_last_n_messages(chat_id, n=10)

        # Push back into Redis for fast access
        self._redis.clear_chat(chat_id)
        if summary:
            self._redis.set_summary(chat_id, summary)
        for msg in last_messages:
            self._redis.add_message(chat_id, msg)

        return {
            "chat_id":      chat_id,
            "summary":      summary,
            "messages":     last_messages,
        }

    # ------------------------------------------------------------------
    # Per-message operations
    # ------------------------------------------------------------------

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """
        Add a message to both Redis (rolling window) and MongoDB (full history).
        """
        msg = {"role": role, "content": content, "metadata": metadata or {}}
        self._redis.add_message(chat_id, msg)
        self._mongo.append_message(chat_id, msg)

    def get_context(self, chat_id: str) -> dict:
        """
        Return the full context for a chat to prepend to Claude prompts:
          - Current session summary (from Redis)
          - Rolling last N messages (from Redis)
        """
        return {
            "summary":  self._redis.get_summary(chat_id),
            "messages": self._redis.get_messages(chat_id),
        }

    def update_schema_context(self, chat_id: str, tables: list[str]) -> None:
        """Track which tables are being queried in this session."""
        existing = self._redis.get_schema_context(chat_id)
        merged = list(dict.fromkeys(existing + tables))  # dedup, preserve order
        self._redis.set_schema_context(chat_id, merged)

    # ------------------------------------------------------------------
    # Cross-session reference resolution (knowledge graph)
    # ------------------------------------------------------------------

    def resolve_cross_session_reference(
        self, chat_id: str, user_message: str
    ) -> dict | None:
        """
        Detect if a user message references a past session and retrieve it.

        Flow:
          1. detect_cross_session_reference() → ReferenceSignal (Haiku call)
          2. If signal fires (confidence >= 0.6):
               a. graph.search_sessions(topic_hint) → top match
               b. graph.get_session_entities(matched_session_id) → entities
               c. graph.link_followup(chat_id, matched_session_id)
          3. Return context dict for injection into the generator prompt.

        Args:
            chat_id:      Current (active) session ID.
            user_message: Raw user message to analyze.

        Returns:
            Context dict with keys {session_id, topic_summary, entities, similarity}
            or None if no cross-session reference detected or graph is disabled.
        """
        if self._graph is None:
            return None

        signal = detect_cross_session_reference(user_message)
        if not signal.is_cross_session_reference or signal.confidence < 0.6:
            return None
        if not signal.topic_hint:
            return None

        matches = self._graph.search_sessions(signal.topic_hint, top_k=1)
        if not matches:
            return None

        top = matches[0]
        if top.similarity < 0.3:  # too low to be useful
            return None

        entities = self._graph.get_session_entities(top.session_id)

        # Record the follow-up relationship in the graph
        try:
            self._graph.link_followup(chat_id, top.session_id)
        except Exception:
            pass

        return {
            "session_id":    top.session_id,
            "topic_summary": top.topic_summary,
            "entities":      entities,
            "similarity":    top.similarity,
        }

    # ------------------------------------------------------------------
    # Old query reference resolution (within-session, kept for compatibility)
    # ------------------------------------------------------------------

    def find_referenced_query(
        self, chat_id: str, reference: str, feedback_manager=None
    ) -> dict | None:
        """
        Search query history for the most relevant past verified query.
        Used for within-session references ("like that query earlier").
        """
        if feedback_manager is None:
            return None

        results = feedback_manager.search_history(reference, limit=5)
        if not results:
            return None

        return sorted(results, key=lambda r: r.get("rating", 0), reverse=True)[0]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _summarize(self, messages: list[dict]) -> str:
        """Summarize a list of messages using Haiku."""
        if not messages:
            return ""

        conversation = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')[:300]}"
            for m in messages
        )

        prompt = f"Conversation to summarize:\n\n{conversation}\n\nSummary:"

        try:
            return run(prompt=prompt, task="summarization", system=_SUMMARIZE_SYSTEM)
        except ClaudeRunnerError:
            # Fallback: extract just the user questions
            questions = [
                m.get("content", "")[:100]
                for m in messages
                if m.get("role") == "user"
            ]
            return "Session covered: " + " | ".join(questions[:5])

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def health(self) -> dict:
        h = {
            "redis":   self._redis.ping(),
            "mongodb": self._mongo.ping(),
        }
        if self._graph is not None:
            h["graph"] = self._graph.ping()
        return h

    def list_chats(self, limit: int = 20) -> list[dict]:
        """List recent chats for the UI sidebar."""
        return self._mongo.list_chats(limit=limit)
