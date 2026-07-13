"""
feedback.py

Closes the improvement loop — saves good queries to SQLite and re-indexes
ChromaDB so future similar questions get better few-shot examples.

This is the flywheel:
  user verifies result → feedback saved → ChromaDB re-indexed →
  next similar question gets this as example → better SQL generated

Also handles the query history log (all queries, regardless of rating)
for audit, debugging, and conversation memory retrieval.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.retriever import Example, Retriever


_DEFAULT_DB_PATH = Path(".vaultsql/queries.db")


@dataclass
class QueryRecord:
    question: str
    sql: str
    tables: list[str]
    model_used: str
    rating: int         # 1 = bad, 3 = ok, 5 = perfect
    correction: str = ""   # user-corrected SQL if rating <= 2
    chat_id: str = ""      # conversation identifier


class FeedbackManager:
    """
    Handles query rating, storage, and ChromaDB re-indexing.

    Usage:
        fm = FeedbackManager(retriever)
        fm.setup()
        fm.record(QueryRecord(...))
    """

    def __init__(
        self,
        retriever: Retriever,
        db_path: Path = _DEFAULT_DB_PATH,
    ) -> None:
        self._retriever = retriever
        self._db_path = db_path

    def setup(self) -> None:
        """Create query history table if it doesn't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self._db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT,
                question    TEXT NOT NULL,
                sql         TEXT NOT NULL,
                tables      TEXT,
                model_used  TEXT,
                rating      INTEGER,
                correction  TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.commit()
        con.close()

    def record(self, record: QueryRecord) -> None:
        """
        Save a query result with its rating.

        - All queries are saved to history (regardless of rating)
        - Queries rated >= 4 are added to ChromaDB as few-shot examples
        - Queries rated <= 2 with a correction save the corrected SQL instead
        """
        sql_to_store = record.correction if record.correction and record.rating <= 2 \
                       else record.sql

        self._save_to_history(record, sql_to_store)

        # Only high-quality queries become few-shot examples
        if record.rating >= 4:
            self._retriever.add(
                Example(
                    question=record.question,
                    sql=sql_to_store,
                    tables=record.tables,
                    rating=record.rating,
                )
            )

    def get_history(
        self,
        chat_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Retrieve query history. Optionally filter by chat_id.
        Used by memory_manager to reconstruct old conversations.
        """
        con = sqlite3.connect(self._db_path)
        if chat_id:
            rows = con.execute(
                "SELECT * FROM query_history WHERE chat_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM query_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        con.close()

        cols = [
            "id", "chat_id", "question", "sql", "tables",
            "model_used", "rating", "correction", "created_at",
        ]
        return [dict(zip(cols, row)) for row in rows]

    def search_history(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        Keyword search over past questions.
        Used when user references an old query mid-conversation.
        """
        con = sqlite3.connect(self._db_path)
        rows = con.execute(
            "SELECT * FROM query_history "
            "WHERE question LIKE ? OR sql LIKE ? "
            "ORDER BY rating DESC, created_at DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
        con.close()

        cols = [
            "id", "chat_id", "question", "sql", "tables",
            "model_used", "rating", "correction", "created_at",
        ]
        return [dict(zip(cols, row)) for row in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save_to_history(self, record: QueryRecord, sql_to_store: str) -> None:
        con = sqlite3.connect(self._db_path)
        con.execute(
            """INSERT INTO query_history
               (chat_id, question, sql, tables, model_used, rating, correction)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.chat_id,
                record.question,
                sql_to_store,
                ",".join(record.tables),
                record.model_used,
                record.rating,
                record.correction,
            ),
        )
        con.commit()
        con.close()
