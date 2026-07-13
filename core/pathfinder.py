"""
pathfinder.py

BFS-based join path discovery on the FK graph produced by introspector.py.

This is the core of the SchemaGraphSQL approach (EACL 2026):
  - No LLM involved here — pure deterministic graph traversal
  - Given anchor tables (from anchor_extractor.py), find the shortest
    join path between them via BFS
  - Returns ordered list of join conditions ready for SQL generation

If no FK path exists between anchor tables, signals joinability.py
to run the LLM-guided implicit join inference step.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from core.introspector import ForeignKey, SchemaSnapshot


@dataclass
class JoinStep:
    """A single JOIN in the discovered path."""
    left_table: str
    right_table: str
    condition: str  # e.g. "users.id = orders.user_id"


@dataclass
class PathResult:
    anchor_tables: list[str]
    all_tables: list[str]       # anchors + intermediate tables in join path
    join_steps: list[JoinStep]  # ordered JOIN sequence
    has_missing_fk: bool = False  # True if any join was inferred (no FK in schema)

    def join_clause(self) -> str:
        """SQL JOIN clause string from the discovered path."""
        if not self.join_steps:
            return ""
        parts = []
        seen = {self.join_steps[0].left_table}
        parts.append(self.join_steps[0].left_table)
        for step in self.join_steps:
            if step.right_table not in seen:
                parts.append(f"JOIN {step.right_table} ON {step.condition}")
                seen.add(step.right_table)
        return " ".join(parts)


class Pathfinder:
    """
    BFS join path discovery on the FK adjacency graph.

    Usage:
        pf = Pathfinder(snapshot)
        result = pf.find(["users", "orders", "products"])
    """

    def __init__(self, snapshot: SchemaSnapshot) -> None:
        self._graph = snapshot.fk_graph
        self._tables = set(snapshot.table_names())

    def find(self, anchor_tables: list[str]) -> PathResult:
        """
        Find join paths connecting all anchor tables.

        Strategy:
          1. Start from the first anchor table
          2. BFS to reach each subsequent anchor table
          3. Accumulate join steps from each BFS path
          4. De-duplicate intermediate tables
        """
        if not anchor_tables:
            return PathResult(anchor_tables=[], all_tables=[], join_steps=[])

        if len(anchor_tables) == 1:
            return PathResult(
                anchor_tables=anchor_tables,
                all_tables=anchor_tables,
                join_steps=[],
            )

        all_join_steps: list[JoinStep] = []
        all_tables: list[str] = [anchor_tables[0]]
        has_missing_fk = False

        # Connect each anchor to the next via BFS
        for i in range(len(anchor_tables) - 1):
            source = anchor_tables[i]
            target = anchor_tables[i + 1]

            path = self._bfs(source, target)

            if path is None:
                # No FK path — signal joinability.py to infer
                has_missing_fk = True
                # Add a placeholder join step that joinability.py will fill in
                all_join_steps.append(
                    JoinStep(
                        left_table=source,
                        right_table=target,
                        condition="",  # empty = needs inference
                    )
                )
                if target not in all_tables:
                    all_tables.append(target)
            else:
                for step in path:
                    all_join_steps.append(step)
                    if step.right_table not in all_tables:
                        all_tables.append(step.right_table)

        return PathResult(
            anchor_tables=anchor_tables,
            all_tables=all_tables,
            join_steps=all_join_steps,
            has_missing_fk=has_missing_fk,
        )

    def _bfs(self, source: str, target: str) -> list[JoinStep] | None:
        """
        BFS from source to target on FK graph.
        Returns ordered list of JoinSteps, or None if no path exists.
        """
        if source not in self._tables or target not in self._tables:
            return None

        if source == target:
            return []

        # BFS: queue holds (current_node, path_of_join_steps)
        queue: deque[tuple[str, list[JoinStep]]] = deque()
        queue.append((source, []))
        visited: set[str] = {source}

        while queue:
            current, path = queue.popleft()

            for neighbour, fk in self._graph.get(current, []):
                if neighbour in visited:
                    continue

                step = JoinStep(
                    left_table=current,
                    right_table=neighbour,
                    condition=fk.join_condition,
                )
                new_path = path + [step]

                if neighbour == target:
                    return new_path

                visited.add(neighbour)
                queue.append((neighbour, new_path))

        return None  # no path found

    def reachable_from(self, table: str, max_hops: int = 3) -> set[str]:
        """
        Return all tables reachable from `table` within max_hops FK edges.
        Used to expand anchor sets when the initial set is too narrow.
        """
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(table, 0)])

        while queue:
            current, hops = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if hops >= max_hops:
                continue
            for neighbour, _ in self._graph.get(current, []):
                if neighbour not in visited:
                    queue.append((neighbour, hops + 1))

        visited.discard(table)
        return visited
