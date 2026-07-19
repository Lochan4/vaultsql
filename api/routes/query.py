"""
POST /api/query — full pipeline: NL → schema linking → SQL → execute → chart
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.routes.connections import load_connection
from core import anchor_extractor, enrichment as enrichment_mod
from core import joinability, pathfinder as pf_mod
from core.complexity_router import route
from core.executor import Executor
from core.generator import generate
from core.introspector import Introspector
from core.visualizer import visualize

router = APIRouter()
_ENRICHMENT_FILE = "enrichment.yaml"


class QueryRequest(BaseModel):
    question: str
    connection_alias: str
    chat_id: str = "default"
    enrichment_path: str = "enrichment.yaml"


class QueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    chart_type: str
    chart_b64: str          # base64 PNG, empty if no chart
    model_used: str
    tables_used: list[str]
    chat_id: str


@router.post("", response_model=QueryResponse)
async def run_query(body: QueryRequest, request: Request):
    connection_string = load_connection(body.connection_alias)

    # 0. Cross-session reference detection (knowledge graph)
    memory_mgr = request.app.state.memory_mgr
    cross_session_context = memory_mgr.resolve_cross_session_reference(
        body.chat_id, body.question
    )

    # 1. Introspect schema
    try:
        inspector = Introspector(connection_string)
        snapshot = inspector.run()
        inspector.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema introspection failed: {e}")

    # 2. Load + merge enrichment
    enrich = enrichment_mod.load(body.enrichment_path)
    snapshot = enrichment_mod.merge(snapshot, enrich)

    # 3. Anchor extraction (Haiku)
    anchors = anchor_extractor.extract(body.question, snapshot)

    # 4. BFS pathfinding on FK graph
    pathfinder = pf_mod.Pathfinder(snapshot)
    path_result = pathfinder.find(anchors)

    # 5. Joinability inference if FK missing
    if path_result.has_missing_fk:
        path_result = joinability.infer_joins(path_result, snapshot)

    # 6. Complexity routing → model tier
    routing = route(body.question, path_result)

    # 7. Few-shot retrieval
    retriever = request.app.state.retriever
    examples = retriever.find(body.question, top_k=3)

    # 8. SQL generation
    gen_result = generate(
        question=body.question,
        snapshot=snapshot,
        path_result=path_result,
        enrichment=enrich,
        examples=examples,
        model=routing.model,
        dialect=snapshot.dialect,
        cross_session_context=cross_session_context,
    )

    if not gen_result.sql:
        raise HTTPException(status_code=500, detail="SQL generation failed.")

    # 9. Execute SQL
    executor = Executor(connection_string)
    exec_result = executor.run(gen_result.sql)
    executor.close()

    if not exec_result.success:
        raise HTTPException(status_code=422, detail=exec_result.error)

    # 10. Visualize
    viz = visualize(exec_result.data, body.question)

    # 11. Update conversation memory
    memory_mgr.add_message(body.chat_id, role="user", content=body.question)
    memory_mgr.add_message(
        body.chat_id,
        role="assistant",
        content=gen_result.explanation,
        metadata={"sql": gen_result.sql, "tables": gen_result.tables_used},
    )
    memory_mgr.update_schema_context(body.chat_id, gen_result.tables_used)

    return QueryResponse(
        question=body.question,
        sql=gen_result.sql,
        explanation=gen_result.explanation,
        columns=exec_result.columns,
        rows=exec_result.data.to_dict(orient="records"),
        row_count=exec_result.row_count,
        truncated=exec_result.truncated,
        chart_type=viz.chart_type.value,
        chart_b64=viz.image_b64,
        model_used=gen_result.model_used,
        tables_used=gen_result.tables_used,
        chat_id=body.chat_id,
    )
