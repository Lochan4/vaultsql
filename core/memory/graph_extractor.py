"""
graph_extractor.py

Two responsibilities:

1. extract_session_knowledge(messages)
   Called at session close. Uses Haiku to extract:
     - topic_summary  (200 words max, what the session was about)
     - entities       (tables, metrics, topics, concepts mentioned)
     - relations      (how entities relate to each other)
   Output is written to the knowledge graph via GraphMemory.

2. detect_cross_session_reference(user_message)
   Called at query time before the main pipeline.
   Uses Haiku to detect if the user is referencing a past session
   ("in that chat where I was asking about X") and extracts the
   topic search signal to feed into GraphMemory.search_sessions().

Both use Haiku via claude_runner — cheap and fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.claude_runner import ClaudeRunnerError, run_json


# ── Prompts ─────────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = """You are a knowledge extraction engine for a SQL assistant.
Given a conversation between a user and an AI SQL assistant, extract structured
knowledge to store in a persistent knowledge graph.

Return JSON with exactly this structure (no markdown, no extra keys):
{
  "topic_summary": "200-word max summary — be specific: mention table names, metrics, questions asked, and key findings",
  "entities": [
    {"name": "exact entity name", "type": "Table|Metric|Topic|Concept", "summary": "one sentence"}
  ],
  "relations": [
    {"subject": "entity name", "predicate": "JOINED_WITH|IS_METRIC_IN|REFERENCED_IN|ANALYZED_BY|FILTERED_BY|COMPARED_TO", "object": "entity name"}
  ]
}

Entity type guide:
  Table   — a database table name (orders, users, products, etc.)
  Metric  — a business metric (revenue, churn, signups, conversion rate, etc.)
  Topic   — a theme or analytical question (monthly trends, regional breakdown, etc.)
  Concept — a business concept (cohort, funnel, retention, etc.)

Extract 3–10 entities and 2–8 relations. Be specific, not generic."""


_DETECTION_SYSTEM = """You are a cross-session reference detector for a SQL assistant.
Determine if the user message references a PAST conversation session (not the current one).

Reference patterns to detect:
  - "in that past chat where I was asking about X"
  - "remember when we talked about X"
  - "like that query we did before about X"
  - "go back to the conversation about X"
  - "similar to what I was doing earlier with X"
  - "in my previous session where X"
  - Vague pronouns referring to something clearly not in the current exchange

Do NOT flag as reference:
  - "as I mentioned earlier" (within current conversation)
  - "like the last query" (could be in current session)
  - Generic phrases with no session reference intent

Return JSON (no markdown):
{
  "is_cross_session_reference": true or false,
  "topic_hint": "the search topic to look up in past sessions, or null",
  "confidence": 0.0 to 1.0
}"""


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class EntityRecord:
    name: str
    type: str   # Table | Metric | Topic | Concept
    summary: str


@dataclass
class RelationRecord:
    subject: str
    predicate: str
    object: str


@dataclass
class SessionKnowledge:
    topic_summary: str
    entities: list[EntityRecord] = field(default_factory=list)
    relations: list[RelationRecord] = field(default_factory=list)


@dataclass
class ReferenceSignal:
    is_cross_session_reference: bool
    topic_hint: str | None
    confidence: float = 0.0


# ── Public functions ──────────────────────────────────────────────────────────

def extract_session_knowledge(messages: list[dict]) -> SessionKnowledge:
    """
    Extract structured knowledge from a completed session's messages.

    Called inside memory_manager.close_chat() after the session summary
    is written to MongoDB. The extracted knowledge is then ingested into
    GraphMemory to power future cross-session retrieval.

    Args:
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts.

    Returns:
        SessionKnowledge with topic_summary, entities, and relations.
        Falls back to a minimal summary on any failure — never raises.
    """
    if not messages:
        return SessionKnowledge(topic_summary="")

    conversation = "\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')[:500]}"
        for m in messages
    )
    prompt = f"Conversation:\n\n{conversation}\n\nExtract knowledge graph data."

    try:
        result = run_json(
            prompt=prompt,
            task="knowledge_extraction",
            system=_EXTRACTION_SYSTEM,
        )

        entities = [
            EntityRecord(
                name=e.get("name", "").strip(),
                type=e.get("type", "Concept"),
                summary=e.get("summary", ""),
            )
            for e in result.get("entities", [])
            if e.get("name", "").strip()
        ]

        relations = [
            RelationRecord(
                subject=r.get("subject", "").strip(),
                predicate=r.get("predicate", "REFERENCED_IN"),
                object=r.get("object", "").strip(),
            )
            for r in result.get("relations", [])
            if r.get("subject", "").strip() and r.get("object", "").strip()
        ]

        return SessionKnowledge(
            topic_summary=result.get("topic_summary", ""),
            entities=entities,
            relations=relations,
        )

    except (ClaudeRunnerError, Exception):
        user_msgs = [
            m.get("content", "")[:100]
            for m in messages
            if m.get("role") == "user"
        ]
        return SessionKnowledge(
            topic_summary="Session covered: " + " | ".join(user_msgs[:5])
        )


def detect_cross_session_reference(user_message: str) -> ReferenceSignal:
    """
    Detect if a user message references a past session.

    Called before the main query pipeline on every incoming user message.
    If the signal fires (is_cross_session_reference=True, confidence >= 0.6),
    the query route uses topic_hint to search the knowledge graph.

    Args:
        user_message: The raw user message to analyze.

    Returns:
        ReferenceSignal. Never raises — returns is_cross_session_reference=False
        on any failure to avoid blocking the main pipeline.
    """
    prompt = (
        f'User message: "{user_message}"\n\n'
        "Does this reference a past conversation session?"
    )

    try:
        result = run_json(
            prompt=prompt,
            task="reference_detection",
            system=_DETECTION_SYSTEM,
        )

        return ReferenceSignal(
            is_cross_session_reference=bool(result.get("is_cross_session_reference", False)),
            topic_hint=result.get("topic_hint"),
            confidence=float(result.get("confidence", 0.0)),
        )

    except (ClaudeRunnerError, Exception):
        return ReferenceSignal(is_cross_session_reference=False, topic_hint=None)
