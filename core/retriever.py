"""
retriever.py

ChromaDB-based few-shot example retrieval.

Role in the pipeline:
  ChromaDB is NOT used for schema linking (that's pathfinder.py).
  It is used ONLY for retrieving similar past verified queries as few-shot
  examples to improve SQL generation accuracy.

  "show me revenue last month" → retrieves past verified queries about
  revenue/time filtering → passes them as examples to generator.py

Storage:
  - SQLite stores verified queries (source of truth, human-readable)
  - ChromaDB indexes them as vectors for semantic search
  - On feedback, both are updated together
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions


_COLLECTION_NAME = "verified_queries"
_DEFAULT_DB_PATH = Path(".vaultsql/queries.db")
_DEFAULT_CHROMA_PATH = Path(".vaultsql/chroma")
_TOP_K = 3


@dataclass
class Example:
    question: str
    sql: str
    tables: list[str]
    rating: int  # 1-5, only queries rated >= 4 are used as examples


class Retriever:
    """
    Manages the ChromaDB index and SQLite store for verified query examples.

    Usage:
        retriever = Retriever()
        retriever.setup()
        examples = retriever.find("how many users signed up last week?")
        retriever.add(Example(...))
    """

    def __init__(
        self,
        db_path: Path = _DEFAULT_DB_PATH,
        chroma_path: Path = _DEFAULT_CHROMA_PATH,
    ) -> None:
        self._db_path = db_path
        self._chroma_path = chroma_path
        self._client: chromadb.Client | None = None
        self._collection: chromadb.Collection | None = None

    def setup(self) -> None:
        """Initialize SQLite + ChromaDB. Call once at startup."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._chroma_path.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find(self, question: str, top_k: int = _TOP_K) -> list[Example]:
        """
        Retrieve the top-k most semantically similar verified past queries.
        Returns empty list if collection is empty or query fails.
        """
        collection = self._get_collection()
        try:
            count = collection.count()
            if count == 0:
                return []

            results = collection.query(
                query_texts=[question],
                n_results=min(top_k, count),
            )
            examples = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i]
                examples.append(
                    Example(
                        question=doc,
                        sql=meta.get("sql", ""),
                        tables=meta.get("tables", "").split(","),
                        rating=int(meta.get("rating", 4)),
                    )
                )
            return examples
        except Exception:
            return []

    def add(self, example: Example) -> None:
        """
        Add a verified query example to both SQLite and ChromaDB.
        Only examples with rating >= 4 are added.
        """
        if example.rating < 4:
            return

        # SQLite — source of truth
        self._sqlite_insert(example)

        # ChromaDB — vector index
        collection = self._get_collection()
        # Use question as the document; SQL and tables as metadata
        import hashlib
        doc_id = hashlib.md5(example.question.encode()).hexdigest()
        collection.upsert(
            ids=[doc_id],
            documents=[example.question],
            metadatas=[{
                "sql": example.sql,
                "tables": ",".join(example.tables),
                "rating": str(example.rating),
            }],
        )

    def count(self) -> int:
        """Return total number of indexed examples."""
        return self._get_collection().count()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        con = sqlite3.connect(self._db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS examples (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                question  TEXT NOT NULL,
                sql       TEXT NOT NULL,
                tables    TEXT,
                rating    INTEGER DEFAULT 4,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.commit()
        con.close()

    def _init_chroma(self) -> None:
        self._client = chromadb.PersistentClient(path=str(self._chroma_path))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=ef,
        )

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            raise RuntimeError("Retriever not initialized. Call setup() first.")
        return self._collection

    def _sqlite_insert(self, example: Example) -> None:
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT INTO examples (question, sql, tables, rating) VALUES (?, ?, ?, ?)",
            (example.question, example.sql, ",".join(example.tables), example.rating),
        )
        con.commit()
        con.close()
