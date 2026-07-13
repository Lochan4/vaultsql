"""
complexity_router.py

Classifies query complexity after schema linking and routes to the
appropriate model tier. Based on the EllieSQL approach (2025).

Runs AFTER pathfinder.py — we know the join depth and anchor tables,
so complexity classification is deterministic (no LLM needed here).

Tiers:
  simple  → single table, COUNT/SUM/AVG, no JOINs    → haiku
  medium  → 1-2 JOINs, GROUP BY, basic filters       → sonnet
  complex → 3+ JOINs, implied subqueries, CTEs       → sonnet (with more examples)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.claude_runner import TASK_MODELS, ModelTier
from core.pathfinder import PathResult


ComplexityLevel = Literal["simple", "medium", "complex"]

# Keywords that signal complex SQL even with few tables
_COMPLEX_SIGNALS = {
    "rank", "percentile", "running total", "cumulative", "rolling",
    "pivot", "transpose", "recursive", "hierarchy", "lag", "lead",
    "nth", "median", "mode", "window", "partition",
    "compared to", "vs", "versus", "year over year", "yoy", "mom",
    "cohort", "retention", "funnel",
}

_MEDIUM_SIGNALS = {
    "group", "per", "each", "by", "breakdown", "split",
    "top", "bottom", "most", "least", "highest", "lowest",
    "average", "avg", "sum", "total", "count",
}


@dataclass
class RoutingDecision:
    complexity: ComplexityLevel
    model: ModelTier
    join_depth: int
    reason: str


def route(question: str, path_result: PathResult) -> RoutingDecision:
    """
    Determine complexity level and model tier for a query.

    Args:
        question:    Raw NL question from the user.
        path_result: Output from pathfinder.py.

    Returns:
        RoutingDecision with complexity level, model, and reason.
    """
    join_depth = len(path_result.join_steps)
    question_lower = question.lower()

    # Check for complex signals first (highest priority)
    matched_complex = [s for s in _COMPLEX_SIGNALS if s in question_lower]
    if matched_complex or join_depth >= 3 or path_result.has_missing_fk:
        return RoutingDecision(
            complexity="complex",
            model=TASK_MODELS["sql_complex"],
            join_depth=join_depth,
            reason=(
                f"Complex signals: {matched_complex}" if matched_complex
                else f"Join depth {join_depth} or inferred FK"
            ),
        )

    # Medium: 1-2 joins OR medium language signals
    matched_medium = [s for s in _MEDIUM_SIGNALS if s in question_lower]
    if join_depth in (1, 2) or (join_depth == 0 and matched_medium):
        return RoutingDecision(
            complexity="medium",
            model=TASK_MODELS["sql_medium"],
            join_depth=join_depth,
            reason=(
                f"Join depth {join_depth}"
                if join_depth > 0
                else f"Aggregation signals: {matched_medium[:3]}"
            ),
        )

    # Simple: single table, no aggregation signals
    return RoutingDecision(
        complexity="simple",
        model=TASK_MODELS["sql_simple"],
        join_depth=join_depth,
        reason="Single table, no complex signals",
    )
