"""
redis_memory.py

Active conversation memory using Redis.

Stores per-chat:
  - Rolling last N messages (fast context window)
  - Claude-generated summary (compressed session state)
  - Active schema context (which tables were used in this session)

All keys are namespaced by chat_id and expire after TTL (default 24h).
Redis is local — no cloud, no cost.
"""

from __future__ import annotations

import json
from datetime import timedelta

import redis

_DEFAULT_TTL = timedelta(hours=24)
_MAX_MESSAGES = 10          # rolling window size
_KEY_MESSAGES  = "vaultsql:chat:{chat_id}:messages"
_KEY_SUMMARY   = "vaultsql:chat:{chat_id}:summary"
_KEY_SCHEMA    = "vaultsql:chat:{chat_id}:schema_ctx"


class RedisMemory:
    """
    Manages active conversation state in Redis.

    Usage:
        mem = RedisMemory()
        mem.add_message(chat_id, {"role": "user", "content": "..."})
        messages = mem.get_messages(chat_id)
        mem.set_summary(chat_id, "User asked about revenue trends...")
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> None:
        self._client = redis.Redis(
            host=host, port=port, db=db, decode_responses=True
        )
        self._ttl = ttl

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(self, chat_id: str, message: dict) -> None:
        """
        Append a message to the rolling window.
        Trims to MAX_MESSAGES. Resets TTL on each write.
        """
        key = _KEY_MESSAGES.format(chat_id=chat_id)
        self._client.rpush(key, json.dumps(message))
        # Keep only the last N messages
        self._client.ltrim(key, -_MAX_MESSAGES, -1)
        self._client.expire(key, int(self._ttl.total_seconds()))

    def get_messages(self, chat_id: str) -> list[dict]:
        """Return the rolling message window for a chat."""
        key = _KEY_MESSAGES.format(chat_id=chat_id)
        raw = self._client.lrange(key, 0, -1)
        return [json.loads(m) for m in raw]

    def clear_messages(self, chat_id: str) -> None:
        self._client.delete(_KEY_MESSAGES.format(chat_id=chat_id))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def set_summary(self, chat_id: str, summary: str) -> None:
        """Store a compressed session summary."""
        key = _KEY_SUMMARY.format(chat_id=chat_id)
        self._client.set(key, summary, ex=int(self._ttl.total_seconds()))

    def get_summary(self, chat_id: str) -> str:
        """Return the current session summary, or empty string."""
        key = _KEY_SUMMARY.format(chat_id=chat_id)
        return self._client.get(key) or ""

    def clear_summary(self, chat_id: str) -> None:
        self._client.delete(_KEY_SUMMARY.format(chat_id=chat_id))

    # ------------------------------------------------------------------
    # Schema context
    # ------------------------------------------------------------------

    def set_schema_context(self, chat_id: str, tables_used: list[str]) -> None:
        """Track which tables have been queried in this session."""
        key = _KEY_SCHEMA.format(chat_id=chat_id)
        self._client.set(
            key, json.dumps(tables_used), ex=int(self._ttl.total_seconds())
        )

    def get_schema_context(self, chat_id: str) -> list[str]:
        key = _KEY_SCHEMA.format(chat_id=chat_id)
        raw = self._client.get(key)
        return json.loads(raw) if raw else []

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def exists(self, chat_id: str) -> bool:
        """Return True if this chat has any active Redis state."""
        return bool(
            self._client.exists(_KEY_MESSAGES.format(chat_id=chat_id))
        )

    def clear_chat(self, chat_id: str) -> None:
        """Delete all Redis keys for a chat (called when archiving to Mongo)."""
        self._client.delete(
            _KEY_MESSAGES.format(chat_id=chat_id),
            _KEY_SUMMARY.format(chat_id=chat_id),
            _KEY_SCHEMA.format(chat_id=chat_id),
        )

    def ping(self) -> bool:
        """Check if Redis is reachable."""
        try:
            return self._client.ping()
        except redis.ConnectionError:
            return False
