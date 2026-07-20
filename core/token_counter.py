"""
core/token_counter.py

Records every LLM call — model, task, cost, token counts — to a local SQLite
table. Used by /api/usage/* endpoints for cost visibility.

All writes are best-effort: a failure here never blocks a query response.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = Path(".vaultsql/usage.db")

# ── Pricing (USD per 1M tokens) ──────────────────────────────────────────────
# Update these when Anthropic changes pricing.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
}

_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}  # Sonnet fallback


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup() -> None:
    """Create the usage_log table if it doesn't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      TEXT    NOT NULL,
                task_type      TEXT    NOT NULL,
                model          TEXT    NOT NULL,
                input_tokens   INTEGER,
                output_tokens  INTEGER,
                cost_usd       REAL,
                chat_id        TEXT,
                db_alias       TEXT
            )
        """)


# ── Record ────────────────────────────────────────────────────────────────────

def record(
    task_type: str,
    model: str,
    *,
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    chat_id: str | None = None,
    db_alias: str | None = None,
) -> None:
    """
    Persist one LLM call to the usage log.

    If cost_usd is not provided but token counts are, compute cost from PRICING.
    If neither is provided, record the call with NULL cost (still useful for counting).
    """
    resolved_cost = cost_usd
    if resolved_cost is None and input_tokens is not None and output_tokens is not None:
        p = PRICING.get(model, _DEFAULT_PRICING)
        resolved_cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_log
                    (timestamp, task_type, model, input_tokens, output_tokens,
                     cost_usd, chat_id, db_alias)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, task_type, model, input_tokens, output_tokens,
                 resolved_cost, chat_id, db_alias),
            )
    except Exception:
        pass  # never block on accounting failure


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_summary() -> dict[str, Any]:
    """Aggregate totals across all recorded calls."""
    if not _DB_PATH.exists():
        return _empty_summary()
    with _connect() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                   AS total_calls,
                SUM(input_tokens)          AS total_input_tokens,
                SUM(output_tokens)         AS total_output_tokens,
                SUM(cost_usd)              AS total_cost_usd
            FROM usage_log
        """).fetchone()

        by_model = conn.execute("""
            SELECT model,
                   COUNT(*)        AS calls,
                   SUM(input_tokens)   AS input_tokens,
                   SUM(output_tokens)  AS output_tokens,
                   SUM(cost_usd)       AS cost_usd
            FROM usage_log
            GROUP BY model
            ORDER BY cost_usd DESC
        """).fetchall()

        by_task = conn.execute("""
            SELECT task_type,
                   COUNT(*)        AS calls,
                   SUM(input_tokens)   AS input_tokens,
                   SUM(output_tokens)  AS output_tokens,
                   SUM(cost_usd)       AS cost_usd
            FROM usage_log
            GROUP BY task_type
            ORDER BY cost_usd DESC
        """).fetchall()

    return {
        "total_calls":         row["total_calls"] or 0,
        "total_input_tokens":  row["total_input_tokens"] or 0,
        "total_output_tokens": row["total_output_tokens"] or 0,
        "total_cost_usd":      round(row["total_cost_usd"] or 0.0, 6),
        "by_model": [_row_to_dict(r) for r in by_model],
        "by_task":  [_row_to_dict(r) for r in by_task],
    }


def get_by_task() -> list[dict[str, Any]]:
    """Per-task breakdown: calls, tokens, cost."""
    if not _DB_PATH.exists():
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT task_type,
                   COUNT(*)             AS calls,
                   SUM(input_tokens)    AS input_tokens,
                   SUM(output_tokens)   AS output_tokens,
                   SUM(cost_usd)        AS cost_usd,
                   AVG(cost_usd)        AS avg_cost_usd
            FROM usage_log
            GROUP BY task_type
            ORDER BY cost_usd DESC
        """).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_by_chat(chat_id: str) -> list[dict[str, Any]]:
    """All LLM calls made within a specific chat session."""
    if not _DB_PATH.exists():
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT timestamp, task_type, model,
                   input_tokens, output_tokens, cost_usd
            FROM usage_log
            WHERE chat_id = ?
            ORDER BY timestamp ASC
        """, (chat_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_recent(limit: int = 50) -> list[dict[str, Any]]:
    """Most recent N calls — useful for debugging."""
    if not _DB_PATH.exists():
        return []
    with _connect() as conn:
        rows = conn.execute("""
            SELECT timestamp, task_type, model,
                   input_tokens, output_tokens, cost_usd,
                   chat_id, db_alias
            FROM usage_log
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Internals ─────────────────────────────────────────────────────────────────

@contextmanager
def _connect():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Round floats so JSON doesn't produce 0.00012300000000000002
    for k, v in d.items():
        if isinstance(v, float):
            d[k] = round(v, 6)
    return d


def _empty_summary() -> dict[str, Any]:
    return {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "by_model": [],
        "by_task": [],
    }
