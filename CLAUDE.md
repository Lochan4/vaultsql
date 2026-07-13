# VaultSQL — CLAUDE.md

## Project Overview
VaultSQL is an open-source text-to-SQL system for small companies. Users connect any database
(PostgreSQL, MySQL, SQLite, MSSQL), ask questions in natural language, and get SQL + results +
charts in a chat interface. The system improves over time via a feedback loop — verified queries
become few-shot examples for future queries.

No Obsidian. No external cloud services. Fully self-hosted.

## Research Grounding
Architecture is based on:
- **SchemaGraphSQL** (EACL 2026) — FK pathfinding for schema linking, zero-shot, training-free
- **EllieSQL** (2025) — complexity-aware routing to model tiers
- **GRASP** (2025) — schema pruning before SQL generation

## Architecture

```
vaultsql/
  core/
    introspector.py       # SQLAlchemy: schema + FK adjacency graph, sample values
    enrichment.py         # Parse enrichment.yaml (synonyms, glossary, descriptions)
    anchor_extractor.py   # Haiku: extract anchor tables from user question
    pathfinder.py         # BFS/Dijkstra on FK graph → join paths (no LLM)
    joinability.py        # Haiku: infer joins where FK is missing
    complexity_router.py  # Classify query as simple/medium/complex → model tier
    retriever.py          # ChromaDB: few-shot example retrieval (past verified queries)
    synthesizer.py        # Generate synthetic NL+SQL pairs at init time
    generator.py          # Sonnet/Opus: SQL generation with subgraph + examples
    executor.py           # Run SQL via SQLAlchemy, return results as DataFrame
    visualizer.py         # Matplotlib: auto-select chart type, return base64 PNG
    feedback.py           # Save good queries to SQLite, re-index ChromaDB
    claude_runner.py      # subprocess wrapper for `claude -p` (no API key needed)
    memory/
      redis_memory.py     # Active conversation: rolling messages + summary (Redis)
      mongo_memory.py     # Long-term storage: full history + summaries (MongoDB)
      memory_manager.py   # Shift logic: Redis ↔ MongoDB
  api/
    main.py               # FastAPI app
    routes/
      query.py            # POST /query — NL → SQL + results + chart
      feedback.py         # POST /feedback — mark query good/bad
      connections.py      # POST /connections — save DB connection
      chat.py             # WebSocket /chat — streaming chat interface
  frontend/
    src/
      components/
        DBConnector.tsx    # Step 1: choose DB type + enter creds
        Chat.tsx           # Main chat interface
        MessageBubble.tsx  # Renders SQL + table + chart in one message
        ChartView.tsx      # Renders base64 matplotlib PNG
      App.tsx
  tests/
    test_introspector.py
    test_pathfinder.py
    test_anchor_extractor.py
    test_generator.py
  example_enrichment.yaml  # Template for new users
  pyproject.toml
  docker-compose.yml       # Redis + MongoDB (optional, for production)
```

## Pipeline (how a query flows)

```
1. User asks NL question
2. anchor_extractor.py  → Haiku extracts anchor tables from question
3. pathfinder.py        → BFS on FK graph finds join paths (deterministic, no LLM)
4. joinability.py       → only if FK missing: Haiku infers implicit joins
5. complexity_router.py → classify simple/medium/complex → pick model tier
6. retriever.py         → ChromaDB finds top-3 similar verified past queries
7. generator.py         → Claude generates SQL with: subgraph + examples + glossary
8. executor.py          → Run SQL, return DataFrame
9. visualizer.py        → Auto-detect chart type, generate matplotlib PNG (base64)
10. feedback.py         → User marks good/bad → good queries saved to SQLite + re-indexed
11. memory_manager.py   → Conversation summary stored in Redis (active) or MongoDB (archived)
```

## Schema Linking — SchemaGraphSQL Approach

Do NOT use embedding similarity for schema linking. Use FK pathfinding.

```python
# Step 1: Anchor extraction (Haiku — cheap, fast)
# Prompt: "Given this question and list of table names, which tables are referenced?"
# Returns: ["users", "orders"]

# Step 2: BFS on FK adjacency graph (pure Python, no LLM)
# fk_graph["users"] = [("orders", "users.id = orders.user_id")]
# BFS from "users" → finds "orders" → join path discovered

# Step 3: Joinability (Haiku — only when FK is missing)
# Prompt: "Do these columns look like they should be joined? users.id, orders.user_id?"
# Returns: yes/no + suggested join condition
```

## Complexity Router — EllieSQL Approach

```
Simple   → single table, COUNT/SUM, no JOINs          → claude-haiku-4-5
Medium   → 1-2 JOINs, GROUP BY, basic filters         → claude-sonnet-4-6
Complex  → 3+ JOINs, subqueries, CTEs, window funcs   → claude-sonnet-4-6 (extended)
```

Router runs AFTER schema linking (knows which tables and join depth).

## Memory Architecture

```
Active chat (Redis, TTL 24h):
  - Last 10 messages (rolling window)
  - Claude-generated conversation summary (200 words max)
  - Active schema context (which tables used in this session)

New chat started:
  1. Claude summarizes current session → 200 words
  2. Full history + summary → MongoDB
  3. Redis session cleared

Old chat resumed:
  1. Load summary + last 10 messages from MongoDB → push to Redis
  2. Continue from Redis (fast access)

User references old query mid-chat:
  1. Detect reference intent
  2. Semantic search against MongoDB query logs
  3. Pull matching query → inject into current Redis context
```

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| LLM calls | `claude -p` subprocess | No API key needed for users |
| Schema linking | BFS on FK graph | SchemaGraphSQL SOTA, deterministic |
| Anchor extraction | claude-haiku-4-5 | Cheap, fast classification |
| SQL generation | claude-sonnet-4-6 | Default; Opus for complex |
| Few-shot retrieval | ChromaDB (local) | Semantic search over past queries only |
| DB connections | SQLAlchemy | PostgreSQL, MySQL, SQLite, MSSQL |
| Active memory | Redis (local) | Fast, TTL-based session memory |
| Long-term memory | MongoDB (local) | Full history, archival |
| Query history | SQLite | Lightweight, zero-config |
| Visualization | Matplotlib → base64 PNG | Rendered in chat, no extra server |
| API | FastAPI | Self-hosted, async |
| Frontend | React + TypeScript | Chat UI with DB connector |

## enrichment.yaml (the only file users edit)

```yaml
tables:
  users:
    description: "registered accounts on the platform"
    synonyms: [people, customers, members, clients]
    columns:
      created_at: "when they signed up"
      plan: "subscription tier: free | starter | pro"

glossary:
  revenue:
    aliases: [make, earn, earnings, income, sales]
    sql_pattern: "SUM(orders.total_amount) WHERE orders.status='completed'"
    maps_to_tables: [orders]
```

## Claude Integration Rules
- Use `claude -p` subprocess via `claude_runner.py` for all LLM calls
- Anchor extraction + joinability → haiku (structured JSON output)
- SQL generation → sonnet (default), opus (complex fallback)
- Always request structured JSON output with `--output-format json`
- Never pass full schema to SQL generator — only the linked subgraph
- Max context: 40k tokens. Trim few-shot examples first if exceeded.

## Coding Standards
- Python 3.11+, type hints everywhere
- Pydantic v2 for all API shapes and config
- No hardcoded credentials — `.env` only
- Single responsibility per module
- Tests mock `claude_runner.py` — never make real subprocess calls in tests
- Keep dependencies minimal for easy self-hosting

## What NOT to do
- Do NOT use embedding similarity for schema linking (use FK pathfinding)
- Do NOT pass the full schema to the SQL generator (pass only linked subgraph)
- Do NOT train any models (zero-shot only, SchemaGraphSQL approach)
- Do NOT require Docker for basic usage (optional for Redis/MongoDB in prod)
- Do NOT add auth to the core — deployer's responsibility

## Build Order
1. `core/introspector.py` — connect to DB, extract schema + FK graph + sample values
2. `core/pathfinder.py` — BFS/Dijkstra on FK adjacency graph
3. `core/anchor_extractor.py` — Haiku call to get anchor tables
4. `core/claude_runner.py` — subprocess wrapper for `claude -p`
5. `core/complexity_router.py` — classify query complexity
6. `core/retriever.py` — ChromaDB few-shot example retrieval
7. `core/generator.py` — full SQL generation
8. `core/executor.py` — run SQL, return DataFrame
9. `core/visualizer.py` — matplotlib chart generation
10. `core/feedback.py` — save verified queries
11. `core/memory/` — Redis + MongoDB memory management
12. `api/` — FastAPI routes
13. `frontend/` — React chat UI
