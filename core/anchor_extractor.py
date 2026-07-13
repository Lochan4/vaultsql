"""
anchor_extractor.py

Uses a cheap Haiku call to extract anchor tables from a user's NL question.
This is Step 1 of the SchemaGraphSQL approach — identify which tables
the question is touching before running BFS pathfinding.

Why LLM here instead of embeddings:
  - Embeddings find semantically similar words but miss intent
  - "how much did we make" → embeddings struggle with "make" → revenue → orders
  - Haiku with table list + synonyms correctly resolves this in one call
  - Haiku is cheap enough that this adds negligible cost
"""

from __future__ import annotations

import json

from core.claude_runner import ClaudeRunnerError, run_json
from core.introspector import SchemaSnapshot


_SYSTEM = """You are a database schema analyst.
Your job is to identify which database tables a natural language question is referring to.
You will be given:
  1. A list of available table names with optional descriptions and synonyms
  2. A user question

Return ONLY a valid JSON object in this exact format:
{
  "anchor_tables": ["table1", "table2"],
  "reasoning": "brief explanation"
}

Rules:
- Only include tables from the provided list
- Include a table if the question directly or indirectly refers to it
- Use synonyms and descriptions to resolve vague language
- If uncertain between two tables, include both
- Never include tables that are clearly unrelated to the question
"""


def _build_table_list(snapshot: SchemaSnapshot) -> str:
    """Format table names + descriptions + synonyms for the prompt."""
    lines = []
    for name, meta in snapshot.tables.items():
        parts = [f"- {name}"]
        if meta.description:
            parts.append(f"({meta.description})")
        if meta.synonyms:
            parts.append(f"[synonyms: {', '.join(meta.synonyms)}]")
        # Add sample column names — helps resolve "revenue" → orders.total_amount
        col_names = ", ".join(meta.column_names()[:8])
        parts.append(f"[columns: {col_names}]")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def extract(question: str, snapshot: SchemaSnapshot) -> list[str]:
    """
    Extract anchor tables from the user question using Haiku.

    Args:
        question: Natural language question from the user.
        snapshot: Introspected schema snapshot.

    Returns:
        List of table names that are anchors for this question.
        Falls back to all table names if extraction fails.
    """
    table_list = _build_table_list(snapshot)

    prompt = f"""Available tables:
{table_list}

User question: "{question}"

Which tables does this question refer to? Return JSON only."""

    try:
        result = run_json(prompt=prompt, task="anchor_extraction", system=_SYSTEM)
        anchors = result.get("anchor_tables", [])

        # Validate — only return tables that actually exist in the snapshot
        valid = [t for t in anchors if t in snapshot.tables]

        # If nothing matched, fall back to all tables (pathfinder handles pruning)
        return valid if valid else snapshot.table_names()

    except (ClaudeRunnerError, KeyError, TypeError):
        # Graceful fallback — never block the pipeline
        return snapshot.table_names()
