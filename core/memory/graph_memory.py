"""
graph_memory.py

Kuzu-based knowledge graph for cross-session chat memory.

Stores structured breakdowns of every chat session so that future sessions can
retrieve relevant past context when a user references it ("that chat about X").

Graph schema
────────────
Node tables:
  Session  — one node per closed chat session
  Entity   — one node per unique named thing (table, metric, topic, concept)

Relationship tables:
  DISCUSSED_IN  Entity → Session   (entity was discussed in this session)
  RELATED_TO    Entity → Entity    (subject predicate object, with timestamps)
  FOLLOWUP_OF   Session → Session  (this session followed up on a prior one)

Embeddings
──────────
Session.topic_embedding and Entity.embedding are stored as FLOAT[384] columns
using the all-MiniLM-L6-v2 model (already a project dependency via ChromaDB).
Retrieval computes cosine similarity in Python/numpy — efficient for small-to-
medium enterprise usage (100s–1000s of sessions).

Usage
─────
    graph = GraphMemory()
    graph.setup()
    graph.ingest_session(session_id, knowledge, db_alias="prod-pg")
    matches = graph.search_sessions("revenue trends by region", top_k=3)
    graph.link_followup(new_session_id, prior_session_id)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import kuzu
    from sentence_transformers import SentenceTransformer

from core.memory.graph_extractor import SessionKnowledge

_DEFAULT_DB_PATH = Path(".vaultsql/graph")
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBED_DIM = 384
_MIN_CONFIDENCE = 0.6   # threshold below which reference detection is ignored


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class SessionMatch:
    session_id: str
    topic_summary: str
    db_alias: str
    similarity: float                     # cosine similarity to query embedding
    matched_entities: list[str] = field(default_factory=list)


# ── Embedding singleton ───────────────────────────────────────────────────────

_embed_model: "SentenceTransformer | None" = None


def _get_embed_model() -> "SentenceTransformer":
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
    return _embed_model


def _embed(text: str) -> list[float]:
    """Embed text to a 384-dim float list."""
    model = _get_embed_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two pre-normalized vectors."""
    av = np.array(a, dtype=np.float32)
    bv = np.array(b, dtype=np.float32)
    return float(np.dot(av, bv))


def _entity_id(name: str, entity_type: str) -> str:
    """Stable, short entity ID from name + type."""
    key = f"{name.lower().strip()}:{entity_type.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


# ── GraphMemory ───────────────────────────────────────────────────────────────

class GraphMemory:
    """
    Kuzu-backed knowledge graph for cross-session memory.

    One GraphMemory instance is shared for the lifetime of the application
    (initialized in api/main.py lifespan and stored on app.state).
    """

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._db: "kuzu.Database | None" = None
        self._conn: "kuzu.Connection | None" = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """
        Initialize Kuzu database and create schema tables.
        Safe to call multiple times (IF NOT EXISTS on all DDL).
        Call once at application startup.
        """
        import kuzu

        self._db_path.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self._db_path))
        self._conn = kuzu.Connection(self._db)

        self._conn.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Session(
                session_id     STRING,
                topic_summary  STRING,
                topic_embedding FLOAT[{_EMBED_DIM}],
                db_alias       STRING,
                created_at     INT64,
                PRIMARY KEY(session_id)
            )
        """)

        self._conn.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Entity(
                entity_id  STRING,
                name       STRING,
                type       STRING,
                summary    STRING,
                embedding  FLOAT[{_EMBED_DIM}],
                updated_at INT64,
                PRIMARY KEY(entity_id)
            )
        """)

        self._conn.execute("""
            CREATE REL TABLE IF NOT EXISTS DISCUSSED_IN(
                FROM Entity TO Session
            )
        """)

        self._conn.execute("""
            CREATE REL TABLE IF NOT EXISTS RELATED_TO(
                FROM Entity TO Entity,
                predicate  STRING,
                valid_at   INT64,
                invalid_at INT64
            )
        """)

        self._conn.execute("""
            CREATE REL TABLE IF NOT EXISTS FOLLOWUP_OF(
                FROM Session TO Session
            )
        """)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn = None
        if self._db:
            self._db = None

    # ── Write operations ──────────────────────────────────────────────────────

    def ingest_session(
        self,
        session_id: str,
        knowledge: SessionKnowledge,
        db_alias: str = "",
    ) -> None:
        """
        Write a closed session and its extracted knowledge into the graph.

        Called by MemoryManager.close_chat() after session archival to MongoDB.
        Idempotent — safe to call again for the same session_id (MERGE semantics).

        Args:
            session_id: Unique chat session identifier.
            knowledge:  Output of graph_extractor.extract_session_knowledge().
            db_alias:   The DB connection alias used in this session.
        """
        conn = self._require_conn()
        now = int(time.time())

        # ── Session node ────────────────────────────────────────────────────
        topic_emb = _embed(knowledge.topic_summary) if knowledge.topic_summary else [0.0] * _EMBED_DIM

        # MERGE: create if not exists, update summary + embedding if exists
        existing = conn.execute(
            "MATCH (s:Session {session_id: $id}) RETURN count(s)",
            parameters={"id": session_id},
        )
        session_exists = existing.get_next()[0] > 0

        if not session_exists:
            conn.execute(
                """
                CREATE (:Session {
                    session_id: $id,
                    topic_summary: $summary,
                    topic_embedding: $emb,
                    db_alias: $alias,
                    created_at: $ts
                })
                """,
                parameters={
                    "id": session_id,
                    "summary": knowledge.topic_summary,
                    "emb": topic_emb,
                    "alias": db_alias,
                    "ts": now,
                },
            )
        else:
            conn.execute(
                """
                MATCH (s:Session {session_id: $id})
                SET s.topic_summary = $summary,
                    s.topic_embedding = $emb
                """,
                parameters={
                    "id": session_id,
                    "summary": knowledge.topic_summary,
                    "emb": topic_emb,
                },
            )

        # ── Entity nodes + DISCUSSED_IN edges ───────────────────────────────
        for entity in knowledge.entities:
            if not entity.name:
                continue
            eid = _entity_id(entity.name, entity.type)
            entity_emb = _embed(f"{entity.name} {entity.summary}")

            e_exists = conn.execute(
                "MATCH (e:Entity {entity_id: $id}) RETURN count(e)",
                parameters={"id": eid},
            ).get_next()[0] > 0

            if not e_exists:
                conn.execute(
                    """
                    CREATE (:Entity {
                        entity_id: $id,
                        name: $name,
                        type: $type,
                        summary: $summary,
                        embedding: $emb,
                        updated_at: $ts
                    })
                    """,
                    parameters={
                        "id": eid,
                        "name": entity.name,
                        "type": entity.type,
                        "summary": entity.summary,
                        "emb": entity_emb,
                        "ts": now,
                    },
                )
            else:
                conn.execute(
                    """
                    MATCH (e:Entity {entity_id: $id})
                    SET e.summary = $summary, e.updated_at = $ts
                    """,
                    parameters={"id": eid, "summary": entity.summary, "ts": now},
                )

            # DISCUSSED_IN edge — only if not already present
            edge_exists = conn.execute(
                """
                MATCH (e:Entity {entity_id: $eid})-[:DISCUSSED_IN]->(s:Session {session_id: $sid})
                RETURN count(*)
                """,
                parameters={"eid": eid, "sid": session_id},
            ).get_next()[0] > 0

            if not edge_exists:
                conn.execute(
                    """
                    MATCH (e:Entity {entity_id: $eid}), (s:Session {session_id: $sid})
                    CREATE (e)-[:DISCUSSED_IN]->(s)
                    """,
                    parameters={"eid": eid, "sid": session_id},
                )

        # ── RELATED_TO edges ─────────────────────────────────────────────────
        for rel in knowledge.relations:
            if not rel.subject or not rel.object:
                continue

            # Find source + target entities by name (case-insensitive match)
            src_result = conn.execute(
                "MATCH (e:Entity) WHERE lower(e.name) = $name RETURN e.entity_id LIMIT 1",
                parameters={"name": rel.subject.lower().strip()},
            )
            tgt_result = conn.execute(
                "MATCH (e:Entity) WHERE lower(e.name) = $name RETURN e.entity_id LIMIT 1",
                parameters={"name": rel.object.lower().strip()},
            )

            if not src_result.has_next() or not tgt_result.has_next():
                continue

            src_id = src_result.get_next()[0]
            tgt_id = tgt_result.get_next()[0]

            # Create RELATED_TO edge (allow duplicates with different predicates)
            dup = conn.execute(
                """
                MATCH (a:Entity {entity_id: $src})-[r:RELATED_TO {predicate: $pred}]->(b:Entity {entity_id: $tgt})
                RETURN count(r)
                """,
                parameters={"src": src_id, "tgt": tgt_id, "pred": rel.predicate},
            ).get_next()[0] > 0

            if not dup:
                conn.execute(
                    """
                    MATCH (a:Entity {entity_id: $src}), (b:Entity {entity_id: $tgt})
                    CREATE (a)-[:RELATED_TO {predicate: $pred, valid_at: $ts, invalid_at: -1}]->(b)
                    """,
                    parameters={
                        "src": src_id,
                        "tgt": tgt_id,
                        "pred": rel.predicate,
                        "ts": now,
                    },
                )

    def link_followup(self, new_session_id: str, prior_session_id: str) -> None:
        """
        Add a FOLLOWUP_OF edge from the new session to the prior session.

        Called by MemoryManager when it detects a cross-session reference was
        resolved — meaning the new session is a follow-up to the prior one.
        """
        conn = self._require_conn()
        conn.execute(
            """
            MATCH (new:Session {session_id: $new_id}), (prior:Session {session_id: $prior_id})
            CREATE (new)-[:FOLLOWUP_OF]->(prior)
            """,
            parameters={"new_id": new_session_id, "prior_id": prior_session_id},
        )

    # ── Search ────────────────────────────────────────────────────────────────

    def search_sessions(
        self,
        topic_hint: str,
        top_k: int = 3,
    ) -> list[SessionMatch]:
        """
        Find past sessions most relevant to a topic hint.

        Two-channel search:
          1. Semantic — cosine similarity on Session.topic_embedding
          2. Entity keyword — find entities matching topic_hint words,
             traverse DISCUSSED_IN to their sessions

        Results are fused by combined score and deduplicated.

        Args:
            topic_hint: The topic to search for (from reference_detector).
            top_k:      Max number of sessions to return.

        Returns:
            List of SessionMatch ordered by relevance (highest first).
        """
        conn = self._require_conn()
        query_emb = _embed(topic_hint)

        # ── Channel 1: semantic search over session topic embeddings ─────────
        result = conn.execute(
            "MATCH (s:Session) RETURN s.session_id, s.topic_summary, s.db_alias, s.topic_embedding"
        )
        semantic_scores: dict[str, tuple[float, str, str]] = {}
        while result.has_next():
            row = result.get_next()
            sid, summary, alias, emb = row[0], row[1], row[2], row[3]
            if emb:
                score = _cosine(query_emb, emb)
                semantic_scores[sid] = (score, summary or "", alias or "")

        # ── Channel 2: entity keyword search ────────────────────────────────
        # Tokenize topic_hint into keywords, search entity names/summaries
        keywords = [w.lower() for w in topic_hint.split() if len(w) > 2]
        entity_session_hits: dict[str, list[str]] = {}

        for keyword in keywords[:5]:  # cap at 5 keywords
            kw_result = conn.execute(
                """
                MATCH (e:Entity)-[:DISCUSSED_IN]->(s:Session)
                WHERE lower(e.name) CONTAINS $kw OR lower(e.summary) CONTAINS $kw
                RETURN s.session_id, e.name
                """,
                parameters={"kw": keyword},
            )
            while kw_result.has_next():
                row = kw_result.get_next()
                sid, entity_name = row[0], row[1]
                entity_session_hits.setdefault(sid, []).append(entity_name)

        # ── Fusion ───────────────────────────────────────────────────────────
        all_session_ids = set(semantic_scores) | set(entity_session_hits)
        matches: list[SessionMatch] = []

        for sid in all_session_ids:
            sem_score, summary, alias = semantic_scores.get(sid, (0.0, "", ""))
            entity_hits = entity_session_hits.get(sid, [])

            # If we don't have summary from semantic channel, fetch it
            if not summary:
                row_result = conn.execute(
                    "MATCH (s:Session {session_id: $id}) RETURN s.topic_summary, s.db_alias",
                    parameters={"id": sid},
                )
                if row_result.has_next():
                    row = row_result.get_next()
                    summary, alias = row[0] or "", row[1] or ""

            # Combined score: semantic + entity keyword bonus
            entity_bonus = min(len(set(entity_hits)) * 0.05, 0.25)
            combined = sem_score + entity_bonus

            matches.append(SessionMatch(
                session_id=sid,
                topic_summary=summary,
                db_alias=alias,
                similarity=round(combined, 4),
                matched_entities=list(set(entity_hits)),
            ))

        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:top_k]

    def get_session_entities(self, session_id: str) -> list[dict]:
        """
        Return all entities linked to a session.

        Used to enrich the context injected into the current prompt
        with the structured knowledge from the referenced past session.
        """
        conn = self._require_conn()
        result = conn.execute(
            """
            MATCH (e:Entity)-[:DISCUSSED_IN]->(s:Session {session_id: $id})
            RETURN e.name, e.type, e.summary
            """,
            parameters={"id": session_id},
        )
        entities = []
        while result.has_next():
            row = result.get_next()
            entities.append({"name": row[0], "type": row[1], "summary": row[2]})
        return entities

    # ── Health ────────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Check if the graph database is reachable."""
        try:
            conn = self._require_conn()
            conn.execute("MATCH (s:Session) RETURN count(s) LIMIT 1")
            return True
        except Exception:
            return False

    def session_count(self) -> int:
        """Return total number of sessions in the graph."""
        try:
            result = self._require_conn().execute("MATCH (s:Session) RETURN count(s)")
            return result.get_next()[0]
        except Exception:
            return 0

    # ── Internal ─────────────────────────────────────────────────────────────

    def _require_conn(self) -> "kuzu.Connection":
        if self._conn is None:
            raise RuntimeError("GraphMemory not initialized. Call setup() first.")
        return self._conn
