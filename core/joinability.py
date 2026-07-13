"""
joinability.py

Haiku-powered implicit join inference for tables that have no FK defined.

This runs ONLY when pathfinder.py returns has_missing_fk=True — meaning
BFS found anchor tables that aren't connected by any FK in the schema.

Common causes:
  - Legacy DBs with no FK constraints defined (but logical joins exist)
  - Denormalized schemas
  - Multi-tenant DBs where FK is enforced at app layer only

Approach: show Haiku the column names of both tables and ask it to infer
the most likely join condition based on naming conventions and column types.
"""

from __future__ import annotations

from core.claude_runner import ClaudeRunnerError, run_json
from core.introspector import SchemaSnapshot
from core.pathfinder import JoinStep, PathResult


_SYSTEM = """You are a database schema expert.
You will be given two database tables (their column names and types) that need to be joined,
but no foreign key constraint is defined between them.

Infer the most likely join condition based on:
- Column naming conventions (e.g. user_id in one table likely joins id in a users table)
- Column data types matching
- Common patterns (created_by, owner_id, account_id, etc.)

Return ONLY valid JSON in this exact format:
{
  "can_join": true,
  "join_condition": "table_a.column = table_b.column",
  "confidence": "high | medium | low",
  "reasoning": "brief explanation"
}

If no plausible join exists, return:
{
  "can_join": false,
  "join_condition": null,
  "confidence": "low",
  "reasoning": "explanation"
}
"""


def _format_table(name: str, snapshot: SchemaSnapshot) -> str:
    if name not in snapshot.tables:
        return f"TABLE {name} (unknown)"
    meta = snapshot.tables[name]
    cols = "\n".join(
        f"  {c.name} ({c.dtype})" for c in meta.columns
    )
    return f"TABLE {name}:\n{cols}"


def infer_joins(path_result: PathResult, snapshot: SchemaSnapshot) -> PathResult:
    """
    For every JoinStep with an empty condition (missing FK), call Haiku
    to infer the join condition. Updates the PathResult in-place.

    Args:
        path_result: Output from pathfinder.py with has_missing_fk=True
        snapshot:    Full schema snapshot

    Returns:
        Updated PathResult with inferred join conditions filled in.
        Steps where inference fails are left with empty conditions
        (generator will handle gracefully).
    """
    if not path_result.has_missing_fk:
        return path_result

    updated_steps: list[JoinStep] = []
    still_missing = False

    for step in path_result.join_steps:
        if step.condition:
            # FK condition already exists — no inference needed
            updated_steps.append(step)
            continue

        # Missing FK — try to infer
        inferred = _infer_single(step.left_table, step.right_table, snapshot)
        if inferred:
            updated_steps.append(
                JoinStep(
                    left_table=step.left_table,
                    right_table=step.right_table,
                    condition=inferred,
                )
            )
        else:
            # Could not infer — keep empty, mark as still missing
            updated_steps.append(step)
            still_missing = True

    path_result.join_steps = updated_steps
    path_result.has_missing_fk = still_missing
    return path_result


def _infer_single(
    left_table: str, right_table: str, snapshot: SchemaSnapshot
) -> str | None:
    """
    Ask Haiku to infer the join condition between two tables.
    Returns the join condition string, or None if inference fails/is low confidence.
    """
    left_fmt = _format_table(left_table, snapshot)
    right_fmt = _format_table(right_table, snapshot)

    prompt = f"""These two tables need to be joined but have no foreign key defined.
Infer the most likely join condition.

{left_fmt}

{right_fmt}

Return JSON only."""

    try:
        result = run_json(prompt=prompt, task="joinability", system=_SYSTEM)

        if not result.get("can_join"):
            return None

        # Skip low-confidence inferences to avoid wrong joins
        if result.get("confidence") == "low":
            return None

        condition = result.get("join_condition", "")
        return condition if condition else None

    except (ClaudeRunnerError, KeyError, TypeError):
        return None
