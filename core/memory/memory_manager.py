"""
memory_manager.py

Orchestrates the Redis ↔ MongoDB shift logic.

Rules:
  - Active chat lives in Redis (fast, TTL-based)
  - When a new chat starts: current Redis session → summarize → archive to MongoDB
  - When an old chat is resumed: load from MongoDB → push to Redis
  - Mid-conversation reference to old query: semantic search in query history,
    inject relevant past query into current Redis context

This is the only module that touches both Redis and MongoDB.
Everything else talks to MemoryManager, not the stores directly.
"""

from __future__ import annotations

from core.claude_runner import ClaudeRunnerError, run
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
    ) -> None:
        self._redis = redis or RedisMemory()
        self._mongo = mongo or MongoMemory()

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
        Archive the active Redis session to MongoDB and clear Redis.

        Steps:
          1. Pull messages from Redis
          2. Claude summarizes the session
          3. Summary + messages → MongoDB
          4. Redis cleared
        """
        messages = self._redis.get_messages(chat_id)
        if not messages:
            return

        summary = self._summarize(messages)
        self._mongo.archive_summary(chat_id, summary)

        # Persist any messages not already in Mongo
        for msg in messages:
            self._mongo.append_message(chat_id, msg)

        self._redis.clear_chat(chat_id)

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
    # Old query reference resolution
    # ------------------------------------------------------------------

    def find_referenced_query(
        self, chat_id: str, reference: str, feedback_manager=None
    ) -> dict | None:
        """
        When a user says "like that query earlier" or "same as before",
        search query history for the most relevant past query.

        Args:
            chat_id:          Current chat session
            reference:        The reference phrase from the user
            feedback_manager: Optional FeedbackManager for history search

        Returns:
            The most relevant past QueryRecord as dict, or None.
        """
        if feedback_manager is None:
            return None

        results = feedback_manager.search_history(reference, limit=5)
        if not results:
            return None

        # Return highest-rated result
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
        return {
            "redis": self._redis.ping(),
            "mongodb": self._mongo.ping(),
        }

    def list_chats(self, limit: int = 20) -> list[dict]:
        """List recent chats for the UI sidebar."""
        return self._mongo.list_chats(limit=limit)
