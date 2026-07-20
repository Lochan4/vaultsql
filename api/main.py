"""
api/main.py

FastAPI application entry point.
All core modules are initialized at startup and shared via app.state.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import chat, connections, feedback, query, usage
from core import token_counter
from core.feedback import FeedbackManager
from core.memory.graph_memory import GraphMemory
from core.memory.memory_manager import MemoryManager
from core.retriever import Retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — initialize shared resources
    token_counter.setup()

    retriever = Retriever()
    retriever.setup()

    feedback_mgr = FeedbackManager(retriever=retriever)
    feedback_mgr.setup()

    graph = GraphMemory()
    graph.setup()

    memory_mgr = MemoryManager(graph=graph)

    app.state.retriever = retriever
    app.state.feedback_mgr = feedback_mgr
    app.state.graph = graph
    app.state.memory_mgr = memory_mgr

    yield

    # Shutdown
    graph.close()


app = FastAPI(
    title="VaultSQL",
    description="Open-source text-to-SQL assistant. Connect any database, ask in plain English.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(query.router,       prefix="/api/query",       tags=["query"])
app.include_router(feedback.router,    prefix="/api/feedback",    tags=["feedback"])
app.include_router(chat.router,        prefix="/api/chat",        tags=["chat"])
app.include_router(usage.router,       prefix="/api/usage",       tags=["usage"])


@app.get("/health")
async def health(request_state=None):
    return {"status": "ok"}
