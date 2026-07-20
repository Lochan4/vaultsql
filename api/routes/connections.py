"""
POST /api/connections — validate + save a database connection,
                        run introspection + synthesis on first connect.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core import enrichment as enrichment_mod
from core.introspector import Introspector
from core.synthesizer import generate as synthesize

router = APIRouter()
_CONNECTIONS_FILE = Path(".vaultsql/connections.json")
_ENRICHMENT_FILE  = Path("enrichment.yaml")


class TestRequest(BaseModel):
    connection_string: str


class TestResponse(BaseModel):
    ok: bool
    dialect: str | None = None
    error: str | None = None


class ConnectionRequest(BaseModel):
    alias: str                  # e.g. "production-pg"
    connection_string: str      # e.g. "postgresql://user:pass@host/db"
    enrichment_path: str = "enrichment.yaml"


class ConnectionResponse(BaseModel):
    alias: str
    dialect: str
    tables: list[str]
    synthetic_examples_added: int


@router.post("/test", response_model=TestResponse)
async def test_connection(body: TestRequest):
    """
    Quick connectivity check — SQLAlchemy connect + SELECT 1 + dispose.
    Does NOT introspect schema or save anything. Called by the UI before save.
    Times out at 5 seconds to avoid hanging the browser.
    """
    try:
        from sqlalchemy import create_engine, text

        kwargs: dict = {}
        cs = body.connection_string
        if "sqlite" in cs:
            pass  # no timeout needed for file-based DB
        elif "pyodbc" in cs or "mssql" in cs:
            kwargs["connect_args"] = {"timeout": 5}
        else:
            # PostgreSQL and MySQL both support connect_timeout
            kwargs["connect_args"] = {"connect_timeout": 5}

        engine = create_engine(cs, **kwargs)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        dialect = engine.dialect.name
        engine.dispose()
        return TestResponse(ok=True, dialect=dialect)
    except Exception as e:
        return TestResponse(ok=False, error=str(e))


@router.post("", response_model=ConnectionResponse)
async def create_connection(body: ConnectionRequest, request: Request):
    """
    Connect to a database, introspect schema, generate synthetic examples.
    Called once when the user sets up a new DB connection in the UI.
    """
    try:
        inspector = Introspector(body.connection_string)
        snapshot = inspector.run()
        inspector.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}") from e

    # Load and merge enrichment
    enrich = enrichment_mod.load(body.enrichment_path)
    snapshot = enrichment_mod.merge(snapshot, enrich)

    # Save connection string (local file — never sent back to client)
    _save_connection(body.alias, body.connection_string)

    # Generate synthetic examples to cold-start ChromaDB
    retriever = request.app.state.retriever
    n_added = synthesize(snapshot, enrich, retriever)

    return ConnectionResponse(
        alias=body.alias,
        dialect=snapshot.dialect,
        tables=snapshot.table_names(),
        synthetic_examples_added=n_added,
    )


@router.get("")
async def list_connections():
    """List saved connection aliases (not the connection strings)."""
    if not _CONNECTIONS_FILE.exists():
        return {"connections": []}
    data = json.loads(_CONNECTIONS_FILE.read_text())
    return {"connections": list(data.keys())}


def _save_connection(alias: str, connection_string: str) -> None:
    _CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _CONNECTIONS_FILE.exists():
        data = json.loads(_CONNECTIONS_FILE.read_text())
    data[alias] = connection_string
    _CONNECTIONS_FILE.write_text(json.dumps(data, indent=2))


def load_connection(alias: str) -> str:
    """Helper used by query route to look up a connection string by alias."""
    if not _CONNECTIONS_FILE.exists():
        raise HTTPException(status_code=404, detail=f"Connection '{alias}' not found.")
    data = json.loads(_CONNECTIONS_FILE.read_text())
    if alias not in data:
        raise HTTPException(status_code=404, detail=f"Connection '{alias}' not found.")
    return data[alias]
