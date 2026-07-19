"""
generator.py

Builds the final SQL generation prompt and calls Claude.

This module receives pre-solved context from the pipeline:
  - Linked subgraph (only relevant tables + join path) from pathfinder
  - Glossary context from enrichment
  - Few-shot examples from retriever
  - Model tier from complexity_router

It does NOT receive the full schema — only the pruned subgraph.
This is critical: passing the full schema degrades SQL accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.claude_runner import ModelTier, run_json
from core.enrichment import Enrichment
from core.introspector import SchemaSnapshot
from core.pathfinder import PathResult
from core.retriever import Example


_SYSTEM = """You are an expert SQL engineer. Generate a single, correct SQL query for the user's question.

Rules:
- Use ONLY the tables and columns provided in the schema context
- Follow the join conditions exactly as specified
- Apply glossary definitions when the user uses business terms
- Use the provided examples as reference for style and patterns
- Return ONLY valid JSON: {"sql": "...", "explanation": "one sentence explanation"}
- Do not add markdown, backticks, or extra text outside the JSON
- Use proper SQL for the dialect specified
- For date arithmetic, use dialect-appropriate functions
"""


@dataclass
class GenerationResult:
    sql: str
    explanation: str
    model_used: ModelTier
    tables_used: list[str]


def generate(
    question: str,
    snapshot: SchemaSnapshot,
    path_result: PathResult,
    enrichment: Enrichment,
    examples: list[Example],
    model: ModelTier,
    dialect: str = "postgresql",
    cross_session_context: dict | None = None,
) -> GenerationResult:
    """
    Generate SQL for the user question using the pre-solved schema context.

    Args:
        question:     Raw NL question from the user.
        snapshot:     Full schema snapshot (used to pull subgraph only).
        path_result:  Output from pathfinder (tables + join conditions).
        enrichment:   Parsed enrichment.yaml (glossary context).
        examples:     Few-shot examples from retriever.
        model:        Model tier from complexity_router.
        dialect:      SQL dialect (postgresql, mysql, sqlite, mssql).

    Returns:
        GenerationResult with SQL and explanation.
    """
    prompt = _build_prompt(
        question=question,
        snapshot=snapshot,
        path_result=path_result,
        enrichment=enrichment,
        examples=examples,
        dialect=dialect,
        cross_session_context=cross_session_context,
    )

    result = run_json(prompt=prompt, task=_task_for_model(model), model=model)

    sql = result.get("sql", "").strip()
    explanation = result.get("explanation", "").strip()

    return GenerationResult(
        sql=sql,
        explanation=explanation,
        model_used=model,
        tables_used=path_result.all_tables,
    )


# ------------------------------------------------------------------
# Prompt construction
# ------------------------------------------------------------------

def _build_prompt(
    question: str,
    snapshot: SchemaSnapshot,
    path_result: PathResult,
    enrichment: Enrichment,
    examples: list[Example],
    dialect: str,
    cross_session_context: dict | None = None,
) -> str:
    parts: list[str] = []

    # 0. Past session context (injected when user referenced a prior session)
    if cross_session_context:
        entity_names = [e["name"] for e in cross_session_context.get("entities", [])]
        entity_str = ", ".join(entity_names[:8]) if entity_names else "none extracted"
        parts.append("[Past session context the user is referencing]")
        parts.append(cross_session_context.get("topic_summary", ""))
        parts.append(f"Key entities from that session: {entity_str}")
        parts.append(
            "Use this context to understand what the user is referring to. "
            "Do NOT copy SQL from it directly — generate fresh SQL for the current question.\n"
        )

    # 1. Dialect
    parts.append(f"SQL dialect: {dialect.upper()}")

    # 2. Schema context — ONLY the linked subgraph, not the full schema
    parts.append("\nRelevant schema:")
    for table_name in path_result.all_tables:
        if table_name in snapshot.tables:
            meta = snapshot.tables[table_name]
            parts.append(meta.to_ddl())
            if meta.description:
                parts.append(f"  -- {meta.description}")

    # 3. Join path
    if path_result.join_steps:
        parts.append("\nJoin conditions:")
        for step in path_result.join_steps:
            if step.condition:
                parts.append(f"  {step.condition}")

    # 4. Sample values for context (helps with filter values)
    sample_lines = []
    for table_name in path_result.all_tables:
        if table_name not in snapshot.tables:
            continue
        for col in snapshot.tables[table_name].columns:
            if col.sample_values:
                sample_lines.append(
                    f"  {table_name}.{col.name}: {', '.join(col.sample_values[:5])}"
                )
    if sample_lines:
        parts.append("\nSample values (for filter reference):")
        parts.extend(sample_lines)

    # 5. Glossary context
    glossary_ctx = enrichment.glossary_context(question)
    if glossary_ctx:
        parts.append(f"\n{glossary_ctx}")

    # 6. Few-shot examples
    if examples:
        parts.append("\nSimilar verified queries (use as reference):")
        for i, ex in enumerate(examples, 1):
            parts.append(f"  Example {i}:")
            parts.append(f"    Q: {ex.question}")
            parts.append(f"    SQL: {ex.sql}")

    # 7. The actual question
    parts.append(f"\nUser question: {question}")
    parts.append("\nReturn JSON only: {\"sql\": \"...\", \"explanation\": \"...\"}")

    return "\n".join(parts)


def _task_for_model(model: ModelTier) -> str:
    if "haiku" in model:
        return "sql_simple"
    if "opus" in model:
        return "sql_complex"
    return "sql_medium"
