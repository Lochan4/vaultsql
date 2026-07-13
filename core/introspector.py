"""
introspector.py

Connects to any SQLAlchemy-supported database and extracts:
  - Table names, column names, types, nullable flags
  - Foreign key relationships as an adjacency graph
  - Sample values for categorical columns (for value-based matching)

This is the foundation — everything else (pathfinder, anchor extractor,
generator) depends on what this module produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


@dataclass
class ColumnMeta:
    name: str
    dtype: str
    nullable: bool
    sample_values: list[str] = field(default_factory=list)
    description: str = ""  # filled in from enrichment.yaml


@dataclass
class ForeignKey:
    from_table: str
    from_col: str
    to_table: str
    to_col: str

    @property
    def join_condition(self) -> str:
        return f"{self.from_table}.{self.from_col} = {self.to_table}.{self.to_col}"


@dataclass
class TableMeta:
    name: str
    columns: list[ColumnMeta] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    description: str = ""        # filled in from enrichment.yaml
    synonyms: list[str] = field(default_factory=list)  # filled in from enrichment.yaml

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def to_ddl(self) -> str:
        """Compact DDL-style string for prompt context."""
        lines = [f"TABLE {self.name}"]
        for col in self.columns:
            nullable = "NULL" if col.nullable else "NOT NULL"
            lines.append(f"  {col.name} {col.dtype} {nullable}")
        for fk in self.foreign_keys:
            lines.append(f"  FK: {fk.from_col} → {fk.to_table}.{fk.to_col}")
        return "\n".join(lines)


@dataclass
class SchemaSnapshot:
    """Full introspected schema + FK graph returned by Introspector.run()"""
    tables: dict[str, TableMeta] = field(default_factory=dict)
    # FK adjacency: table → list of (neighbour_table, ForeignKey)
    fk_graph: dict[str, list[tuple[str, ForeignKey]]] = field(default_factory=dict)
    dialect: str = ""

    def table_names(self) -> list[str]:
        return list(self.tables.keys())

    def get_subgraph(self, table_names: list[str]) -> dict[str, TableMeta]:
        """Return only the TableMeta objects for the given table names."""
        return {t: self.tables[t] for t in table_names if t in self.tables}


# Max distinct values sampled per categorical column
_SAMPLE_LIMIT = 15
# Only sample columns with low cardinality (skip IDs, free-text)
_CARDINALITY_THRESHOLD = 50


class Introspector:
    """
    Connects to a database and produces a SchemaSnapshot.

    Usage:
        snapshot = Introspector("postgresql://user:pass@localhost/mydb").run()
    """

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._engine: Engine | None = None

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._connection_string)
        return self._engine

    def run(self) -> SchemaSnapshot:
        engine = self._get_engine()
        inspector = inspect(engine)
        dialect = engine.dialect.name

        tables: dict[str, TableMeta] = {}
        all_fks: list[ForeignKey] = []

        for table_name in inspector.get_table_names():
            columns = self._extract_columns(inspector, engine, table_name)
            fks = self._extract_foreign_keys(inspector, table_name)
            all_fks.extend(fks)
            tables[table_name] = TableMeta(
                name=table_name,
                columns=columns,
                foreign_keys=fks,
            )

        fk_graph = self._build_fk_graph(all_fks, list(tables.keys()))

        return SchemaSnapshot(tables=tables, fk_graph=fk_graph, dialect=dialect)

    def _extract_columns(
        self, inspector: Any, engine: Engine, table_name: str
    ) -> list[ColumnMeta]:
        cols = []
        for col in inspector.get_columns(table_name):
            sample_values = self._sample_values(engine, table_name, col["name"])
            cols.append(
                ColumnMeta(
                    name=col["name"],
                    dtype=str(col["type"]),
                    nullable=col.get("nullable", True),
                    sample_values=sample_values,
                )
            )
        return cols

    def _sample_values(
        self, engine: Engine, table_name: str, column_name: str
    ) -> list[str]:
        """
        Pull a small sample of distinct values for low-cardinality columns.
        Used for value-based matching (e.g. "premium users" → users.plan = 'premium').
        Skips columns with too many distinct values (IDs, free-text, etc.).
        """
        try:
            with engine.connect() as conn:
                # Check cardinality first — avoid sampling huge columns
                count_result = conn.execute(
                    text(
                        f"SELECT COUNT(DISTINCT {column_name}) FROM {table_name}"  # noqa: S608
                    )
                )
                cardinality = count_result.scalar() or 0

                if cardinality > _CARDINALITY_THRESHOLD:
                    return []

                result = conn.execute(
                    text(
                        f"SELECT DISTINCT {column_name} FROM {table_name} "  # noqa: S608
                        f"WHERE {column_name} IS NOT NULL LIMIT {_SAMPLE_LIMIT}"
                    )
                )
                return [str(row[0]) for row in result if row[0] is not None]
        except Exception:
            # Sampling is best-effort — never break introspection
            return []

    def _extract_foreign_keys(
        self, inspector: Any, table_name: str
    ) -> list[ForeignKey]:
        fks = []
        for fk in inspector.get_foreign_keys(table_name):
            if not fk.get("constrained_columns") or not fk.get("referred_columns"):
                continue
            fks.append(
                ForeignKey(
                    from_table=table_name,
                    from_col=fk["constrained_columns"][0],
                    to_table=fk["referred_table"],
                    to_col=fk["referred_columns"][0],
                )
            )
        return fks

    def _build_fk_graph(
        self, all_fks: list[ForeignKey], table_names: list[str]
    ) -> dict[str, list[tuple[str, ForeignKey]]]:
        """
        Build undirected FK adjacency graph.
        Both directions are stored so BFS can traverse either way.

        graph["users"] = [("orders", ForeignKey(users.id → orders.user_id)), ...]
        """
        graph: dict[str, list[tuple[str, ForeignKey]]] = {t: [] for t in table_names}

        for fk in all_fks:
            if fk.from_table in graph:
                graph[fk.from_table].append((fk.to_table, fk))
            if fk.to_table in graph:
                # reverse direction — undirected traversal
                reverse_fk = ForeignKey(
                    from_table=fk.to_table,
                    from_col=fk.to_col,
                    to_table=fk.from_table,
                    to_col=fk.from_col,
                )
                graph[fk.to_table].append((fk.from_table, reverse_fk))

        return graph

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None
