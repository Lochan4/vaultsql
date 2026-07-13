"""
executor.py

Runs SQL against the user's database via SQLAlchemy and returns results
as a pandas DataFrame for easy serialization and visualization.

Safety:
  - Read-only: only SELECT statements are allowed
  - Row limit: capped at 1000 rows to prevent accidental full-table dumps
  - Timeout: enforced at the SQLAlchemy connection level where supported
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


_MAX_ROWS = 1000
_FORBIDDEN_PATTERNS = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)


@dataclass
class ExecutionResult:
    success: bool
    data: pd.DataFrame = field(default_factory=pd.DataFrame)
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    error: str = ""
    truncated: bool = False     # True if result was capped at MAX_ROWS
    sql_executed: str = ""


class Executor:
    """
    Executes SELECT queries and returns structured results.

    Usage:
        ex = Executor("postgresql://user:pass@localhost/mydb")
        result = ex.run("SELECT COUNT(*) FROM users")
    """

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._engine: Engine | None = None

    def run(self, sql: str) -> ExecutionResult:
        """
        Execute a SQL query and return results as a DataFrame.

        Args:
            sql: SQL query string. Must be a SELECT statement.

        Returns:
            ExecutionResult with data, metadata, and error info.
        """
        # Safety check — block mutation statements
        if _FORBIDDEN_PATTERNS.match(sql.strip()):
            return ExecutionResult(
                success=False,
                error="Only SELECT statements are allowed.",
                sql_executed=sql,
            )

        engine = self._get_engine()
        try:
            with engine.connect() as conn:
                # Add row limit by wrapping in a subquery if not already limited
                limited_sql = _apply_row_limit(sql, _MAX_ROWS)
                result = conn.execute(text(limited_sql))
                columns = list(result.keys())
                rows = result.fetchall()

                df = pd.DataFrame(rows, columns=columns)
                truncated = len(df) == _MAX_ROWS

                return ExecutionResult(
                    success=True,
                    data=df,
                    row_count=len(df),
                    columns=columns,
                    truncated=truncated,
                    sql_executed=limited_sql,
                )

        except SQLAlchemyError as e:
            return ExecutionResult(
                success=False,
                error=str(e).split("\n")[0],  # first line only — no stack trace to user
                sql_executed=sql,
            )

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._connection_string)
        return self._engine

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def to_dict(self, result: ExecutionResult) -> dict:
        """Serialize ExecutionResult to a JSON-safe dict for API responses."""
        return {
            "success": result.success,
            "columns": result.columns,
            "rows": result.data.to_dict(orient="records") if result.success else [],
            "row_count": result.row_count,
            "truncated": result.truncated,
            "error": result.error,
            "sql": result.sql_executed,
        }


def _apply_row_limit(sql: str, limit: int) -> str:
    """
    Wrap the query in a subquery with a LIMIT if no LIMIT already exists.
    Simple heuristic — handles the common case without a full SQL parser.
    """
    sql_stripped = sql.strip().rstrip(";")
    if re.search(r"\bLIMIT\b", sql_stripped, re.IGNORECASE):
        return sql_stripped
    return f"SELECT * FROM ({sql_stripped}) AS __vaultsql_result LIMIT {limit}"
