"""
synthesizer.py

Generates synthetic NL+SQL pairs at init time to cold-start the retriever.

Problem: on day one, ChromaDB is empty — no past examples to retrieve.
Solution: use Claude (via claude -p) to generate diverse question/SQL pairs
          for each table in the schema. These seed the retriever so the
          system is useful immediately.

Runs once during `vaultsql init`. User can re-run with `vaultsql synthesize`.
Synthetic examples are rated 4 (good but not verified) so they're used
as few-shot examples but can be overridden by real verified queries over time.
"""

from __future__ import annotations

import json

from core.claude_runner import ClaudeRunnerError, run_json
from core.enrichment import Enrichment
from core.introspector import SchemaSnapshot, TableMeta
from core.retriever import Example, Retriever


_SYSTEM = """You are a SQL expert generating training data for a text-to-SQL system.
Given a database table schema, generate diverse natural language questions and
their correct SQL queries.

Requirements:
- Cover different query types: COUNT, SUM, AVG, filters, GROUP BY, ORDER BY
- Use realistic business language (not technical SQL terms)
- Include time-based queries where date columns exist
- If glossary terms are provided, generate questions using those terms
- Make questions sound like they come from a non-technical business user

Return ONLY valid JSON as an array:
[
  {"question": "...", "sql": "...", "type": "simple|medium|complex"},
  ...
]
"""

_PAIRS_PER_TABLE = 8
_PAIRS_FOR_JOINS = 5


def generate(
    snapshot: SchemaSnapshot,
    enrichment: Enrichment,
    retriever: Retriever,
) -> int:
    """
    Generate synthetic examples for all tables and add to retriever.

    Returns the total number of examples added.
    """
    total = 0

    # Single-table examples for each table
    for table_name, table_meta in snapshot.tables.items():
        examples = _generate_for_table(table_name, table_meta, enrichment)
        for ex in examples:
            retriever.add(ex)
        total += len(examples)

    # Cross-table (join) examples for connected table pairs
    join_examples = _generate_join_examples(snapshot, enrichment)
    for ex in join_examples:
        retriever.add(ex)
    total += len(join_examples)

    return total


def _generate_for_table(
    table_name: str,
    meta: TableMeta,
    enrichment: Enrichment,
) -> list[Example]:
    """Generate synthetic single-table examples."""
    ddl = meta.to_ddl()

    # Find glossary terms relevant to this table
    table_glossary = [
        t for t in enrichment.glossary
        if table_name in t.maps_to_tables
    ]
    glossary_block = ""
    if table_glossary:
        lines = ["Glossary terms for this table:"]
        for t in table_glossary:
            lines.append(f"  - {t.term}: {t.definition} (aliases: {', '.join(t.aliases)})")
            if t.sql_pattern:
                lines.append(f"    SQL pattern: {t.sql_pattern}")
        glossary_block = "\n" + "\n".join(lines)

    prompt = f"""Generate {_PAIRS_PER_TABLE} diverse question/SQL pairs for this table.

Schema:
{ddl}
{glossary_block}

Return JSON array only."""

    return _call_and_parse(prompt, [table_name])


def _generate_join_examples(
    snapshot: SchemaSnapshot,
    enrichment: Enrichment,
) -> list[Example]:
    """Generate examples for connected table pairs (FK joins)."""
    examples: list[Example] = []
    visited_pairs: set[frozenset] = set()

    for table_name, neighbours in snapshot.fk_graph.items():
        for neighbour_name, fk in neighbours:
            pair = frozenset({table_name, neighbour_name})
            if pair in visited_pairs:
                continue
            visited_pairs.add(pair)

            left = snapshot.tables.get(table_name)
            right = snapshot.tables.get(neighbour_name)
            if not left or not right:
                continue

            prompt = f"""Generate {_PAIRS_FOR_JOINS} question/SQL pairs that JOIN these two tables.

{left.to_ddl()}

{right.to_ddl()}

Join condition: {fk.join_condition}

Return JSON array only."""

            pairs = _call_and_parse(prompt, [table_name, neighbour_name])
            examples.extend(pairs)

    return examples


def _call_and_parse(prompt: str, tables: list[str]) -> list[Example]:
    """Call Claude and parse the returned JSON into Example objects."""
    try:
        raw = run_json(prompt=prompt, task="synthesis", system=_SYSTEM)

        if not isinstance(raw, list):
            return []

        examples = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = item.get("question", "").strip()
            s = item.get("sql", "").strip()
            if q and s:
                examples.append(
                    Example(question=q, sql=s, tables=tables, rating=4)
                )
        return examples

    except (ClaudeRunnerError, json.JSONDecodeError, TypeError):
        return []
