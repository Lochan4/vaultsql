"""
mongo_memory.py

Long-term conversation storage in MongoDB.

Stores:
  - Full message history per chat (all messages, not just rolling window)
  - Session summaries (archived from Redis on chat close)
  - Chat metadata (created_at, db_connection alias, tables queried)

MongoDB is local — self-hosted, no cloud dependency.
Collections:
  - vaultsql.chats        — one doc per chat session (metadata + summary)
  - vaultsql.messages     — one doc per message (references chat_id)
"""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection


_DB_NAME    = "vaultsql"
_CHATS_COL  = "chats"
_MSGS_COL   = "messages"


class MongoMemory:
    """
    Long-term conversation store using MongoDB.

    Usage:
        mongo = MongoMemory()
        mongo.create_chat(chat_id, db_alias="production-pg")
        mongo.append_message(chat_id, {"role": "user", "content": "..."})
        mongo.archive_summary(chat_id, summary="User explored revenue...")
        history = mongo.get_chat_messages(chat_id)
    """

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
    ) -> None:
        self._client = MongoClient(uri)
        self._db = self._client[_DB_NAME]

    @property
    def _chats(self) -> Collection:
        return self._db[_CHATS_COL]

    @property
    def _messages(self) -> Collection:
        return self._db[_MSGS_COL]

    # ------------------------------------------------------------------
    # Chat lifecycle
    # ------------------------------------------------------------------

    def create_chat(self, chat_id: str, db_alias: str = "") -> None:
        """Create a new chat document if it doesn't exist."""
        self._chats.update_one(
            {"chat_id": chat_id},
            {"$setOnInsert": {
                "chat_id":    chat_id,
                "db_alias":   db_alias,
                "summary":    "",
                "created_at": datetime.now(tz=timezone.utc),
                "updated_at": datetime.now(tz=timezone.utc),
            }},
            upsert=True,
        )

    def archive_summary(self, chat_id: str, summary: str) -> None:
        """
        Store the Redis-generated session summary in MongoDB.
        Called when a chat is closed or a new chat is started.
        """
        self._chats.update_one(
            {"chat_id": chat_id},
            {"$set": {
                "summary":    summary,
                "updated_at": datetime.now(tz=timezone.utc),
            }},
            upsert=True,
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def append_message(self, chat_id: str, message: dict) -> None:
        """Append a message to the chat's full history."""
        self._messages.insert_one({
            "chat_id":    chat_id,
            "role":       message.get("role", "user"),
            "content":    message.get("content", ""),
            "metadata":   message.get("metadata", {}),  # sql, tables, chart, etc.
            "created_at": datetime.now(tz=timezone.utc),
        })
        # Update chat updated_at
        self._chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"updated_at": datetime.now(tz=timezone.utc)}},
        )

    def get_chat_messages(
        self,
        chat_id: str,
        limit: int = 50,
        skip: int = 0,
    ) -> list[dict]:
        """
        Retrieve full message history for a chat.
        Returns most recent `limit` messages after skipping `skip`.
        """
        cursor = (
            self._messages
            .find({"chat_id": chat_id}, {"_id": 0})
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        # Reverse so oldest-first for chat display
        return list(reversed(list(cursor)))

    def get_last_n_messages(self, chat_id: str, n: int = 10) -> list[dict]:
        """Return the last N messages for a chat (for Redis restore)."""
        cursor = (
            self._messages
            .find({"chat_id": chat_id}, {"_id": 0})
            .sort("created_at", DESCENDING)
            .limit(n)
        )
        return list(reversed(list(cursor)))

    # ------------------------------------------------------------------
    # Chat listing + retrieval
    # ------------------------------------------------------------------

    def get_chat_summary(self, chat_id: str) -> str:
        """Return the archived summary for a chat."""
        doc = self._chats.find_one({"chat_id": chat_id}, {"_id": 0, "summary": 1})
        return doc.get("summary", "") if doc else ""

    def get_db_alias(self, chat_id: str) -> str:
        """Return the DB connection alias used in a chat session."""
        doc = self._chats.find_one({"chat_id": chat_id}, {"_id": 0, "db_alias": 1})
        return doc.get("db_alias", "") if doc else ""

    def list_chats(self, limit: int = 20) -> list[dict]:
        """List most recent chats (for chat history sidebar in UI)."""
        cursor = (
            self._chats
            .find({}, {"_id": 0, "chat_id": 1, "summary": 1,
                       "created_at": 1, "updated_at": 1, "db_alias": 1})
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    def ping(self) -> bool:
        """Check if MongoDB is reachable."""
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            return False
