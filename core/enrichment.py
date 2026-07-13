"""
enrichment.py

Parses enrichment.yaml and merges business context into a SchemaSnapshot.

enrichment.yaml is the only file users need to edit — it adds:
  - Table descriptions and synonyms (for anchor extraction)
  - Column descriptions (for schema linking context)
  - Business glossary terms (maps vague language → SQL patterns)

After merging, the SchemaSnapshot's tables carry full business context
so anchor_extractor and generator have richer prompts to work with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.introspector import SchemaSnapshot, TableMeta


@dataclass
class GlossaryTerm:
    term: str
    definition: str
    aliases: list[str] = field(default_factory=list)
    sql_pattern: str = ""
    maps_to_tables: list[str] = field(default_factory=list)

    def matches(self, word: str) -> bool:
        """Return True if word matches this term or any alias (case-insensitive)."""
        word_lower = word.lower()
        return word_lower == self.term.lower() or word_lower in [
            a.lower() for a in self.aliases
        ]


@dataclass
class Enrichment:
    """Parsed contents of enrichment.yaml."""
    table_meta: dict[str, dict]        # raw table overrides
    glossary: list[GlossaryTerm]       # business glossary terms
    model_overrides: dict[str, str]    # optional model config

    def find_glossary_terms(self, question: str) -> list[GlossaryTerm]:
        """Find all glossary terms referenced in the question."""
        words = question.lower().split()
        matched = []
        for term in self.glossary:
            for word in words:
                if term.matches(word):
                    matched.append(term)
                    break
        # Also check multi-word aliases
        for term in self.glossary:
            for alias in term.aliases:
                if len(alias.split()) > 1 and alias.lower() in question.lower():
                    if term not in matched:
                        matched.append(term)
        return matched

    def glossary_context(self, question: str) -> str:
        """
        Return a formatted string of relevant glossary terms for use in prompts.
        Empty string if no terms match.
        """
        terms = self.find_glossary_terms(question)
        if not terms:
            return ""
        lines = ["Business glossary (use these definitions when generating SQL):"]
        for t in terms:
            lines.append(f"  - {t.term}: {t.definition}")
            if t.sql_pattern:
                lines.append(f"    SQL pattern: {t.sql_pattern}")
        return "\n".join(lines)


def load(path: str | Path) -> Enrichment:
    """
    Parse enrichment.yaml from disk.

    Returns an empty Enrichment if file doesn't exist — enrichment is optional.
    """
    p = Path(path)
    if not p.exists():
        return Enrichment(table_meta={}, glossary=[], model_overrides={})

    with p.open() as f:
        raw = yaml.safe_load(f) or {}

    # Parse glossary
    glossary: list[GlossaryTerm] = []
    for term_name, term_data in (raw.get("glossary") or {}).items():
        glossary.append(
            GlossaryTerm(
                term=term_name,
                definition=term_data.get("definition", ""),
                aliases=term_data.get("aliases", []),
                sql_pattern=term_data.get("sql_pattern", ""),
                maps_to_tables=term_data.get("maps_to_tables", []),
            )
        )

    return Enrichment(
        table_meta=raw.get("tables") or {},
        glossary=glossary,
        model_overrides=raw.get("models") or {},
    )


def merge(snapshot: SchemaSnapshot, enrichment: Enrichment) -> SchemaSnapshot:
    """
    Inject enrichment context into the SchemaSnapshot in-place.

    Adds descriptions and synonyms to TableMeta and ColumnMeta objects
    so downstream modules (anchor_extractor, generator) get richer context
    without needing to know about enrichment.yaml themselves.
    """
    for table_name, table_overrides in enrichment.table_meta.items():
        if table_name not in snapshot.tables:
            continue

        table: TableMeta = snapshot.tables[table_name]

        if desc := table_overrides.get("description"):
            table.description = desc

        if synonyms := table_overrides.get("synonyms"):
            table.synonyms = synonyms

        # Merge column descriptions
        col_overrides: dict = table_overrides.get("columns") or {}
        for col in table.columns:
            if col_desc := col_overrides.get(col.name):
                col.description = col_desc

    return snapshot
