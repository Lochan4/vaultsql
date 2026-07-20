# VaultSQL

**Open-source, self-hosted Text-to-SQL assistant powered by Claude.**  
Connect any database. Ask questions in natural language. Get SQL, results, and charts — all locally, no cloud required.

---

## What It Does

VaultSQL turns natural language questions into validated SQL queries against your own database. It introspects your schema, learns your business vocabulary, improves from feedback, and remembers your past conversations — entirely on your own infrastructure.

```
"Show me total revenue by customer segment this quarter"
        ↓
  Schema-aware SQL generation
        ↓
  SELECT segment, SUM(total) FROM orders
  JOIN customers ON ... WHERE ... GROUP BY ...
        ↓
  Results table + auto-generated chart
```

---

## Key Capabilities

### Natural Language to SQL
- Converts plain-English questions into accurate SQL queries
- **Schema-linked, not embedding-matched** — uses FK pathfinding (SchemaGraphSQL approach) to find join paths deterministically, without LLM hallucination
- Complexity-aware model routing: Haiku for simple queries, Sonnet for multi-join queries

### Multi-Database Support
| Database | Driver |
|----------|--------|
| PostgreSQL | psycopg2 |
| MySQL | pymysql |
| SQLite | built-in |
| MS SQL Server | pyodbc |

### Three-Tier Memory
| Layer | Technology | Purpose |
|-------|-----------|---------|
| Active session | Redis (TTL 24h) | Rolling message window + live summary |
| Long-term archive | MongoDB | Full chat history, searchable |
| Knowledge graph | Kuzu | Cross-session semantic + entity search |

Ask "in that past chat about revenue trends" and VaultSQL finds the right session via dual-channel graph search (cosine similarity + entity keyword traversal).

### Feedback Loop
- Rate any result 1–5 stars
- High-rated queries (≥ 4) get added to ChromaDB as few-shot examples
- Future queries on similar topics automatically benefit from verified past SQL

### Business Context Layer
- Single `enrichment.yaml` file for table/column descriptions, synonyms, and glossary
- Glossary terms map plain language ("revenue", "churn") to SQL patterns

---

## Architecture

```
vaultsql/
├── api/                      FastAPI application
│   ├── main.py               App init, lifespan, CORS, route registration
│   └── routes/
│       ├── query.py          POST /api/query — full NL→SQL pipeline
│       ├── feedback.py       POST /api/feedback — rating + ChromaDB re-index
│       ├── connections.py    POST /api/connections — connect, introspect, synthesize
│       └── chat.py           GET /api/chat/* — memory + cross-session search
│
├── core/                     Business logic
│   ├── introspector.py       SQLAlchemy: schema extraction + FK adjacency graph
│   ├── enrichment.py         Parse enrichment.yaml, merge into schema snapshot
│   ├── anchor_extractor.py   Haiku: identify anchor tables from question
│   ├── pathfinder.py         BFS join-path discovery (no LLM)
│   ├── joinability.py        Haiku: infer joins where FK is missing
│   ├── complexity_router.py  Classify query → model tier (Haiku / Sonnet)
│   ├── retriever.py          ChromaDB: few-shot example retrieval
│   ├── synthesizer.py        Generate synthetic NL+SQL pairs at first connect
│   ├── generator.py          Sonnet/Opus: SQL generation with full context
│   ├── executor.py           Run SQL safely (SELECT-only, 1000-row limit)
│   ├── visualizer.py         Matplotlib: auto-select chart type → base64 PNG
│   ├── feedback.py           Record ratings, trigger ChromaDB re-index
│   ├── claude_runner.py      subprocess wrapper for `claude -p` (no API key)
│   └── memory/
│       ├── redis_memory.py   Active session: rolling messages + summary
│       ├── mongo_memory.py   Long-term archival: full history
│       ├── graph_memory.py   Kuzu knowledge graph: cross-session entities
│       ├── graph_extractor.py  Knowledge extraction + reference detection
│       └── memory_manager.py   Orchestrates all memory layers
│
└── frontend/                 React + TypeScript UI
    └── src/
        ├── components/
        │   ├── DBConnector.tsx   DB connection form (PostgreSQL/MySQL/SQLite/MSSQL)
        │   ├── Chat.tsx          Main chat interface
        │   ├── MessageBubble.tsx SQL block + result table + chart in one message
        │   ├── SQLBlock.tsx      Syntax-highlighted SQL with copy button
        │   ├── ResultTable.tsx   Paginated results table
        │   ├── ChartView.tsx     Renders base64 matplotlib charts
        │   └── layout/
        │       ├── Sidebar.tsx   Chat history + session search
        │       └── TopBar.tsx    Connection status + model indicator
        ├── store/
        │   ├── chat.ts           Zustand: active chat state
        │   └── connection.ts     Zustand: connection state
        └── lib/
            └── api.ts            Typed API client for all endpoints
```

### Query Pipeline

```
User question
    │
    ├─ 0. Cross-session reference detection (Haiku + Kuzu graph search)
    │
    ├─ 1. Anchor extraction          Haiku identifies relevant tables
    │
    ├─ 2. FK pathfinding             BFS on FK graph → join paths (no LLM)
    │
    ├─ 3. Joinability inference      Haiku infers joins where FK is missing
    │
    ├─ 4. Complexity routing         Classify → pick model tier
    │
    ├─ 5. Few-shot retrieval         ChromaDB finds top-3 similar past queries
    │
    ├─ 6. SQL generation             Sonnet/Opus with subgraph + examples + glossary
    │
    ├─ 7. SQL execution              SQLAlchemy (SELECT-only, 1000-row cap)
    │
    ├─ 8. Visualization              Matplotlib auto-chart → base64 PNG
    │
    └─ 9. Memory update              Redis (active) + MongoDB (archive) + Kuzu (graph)
```

---

## API Reference

### Connections
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/connections/test` | Test connectivity (5s timeout), returns `{ok, dialect}` |
| `POST` | `/api/connections` | Connect DB, introspect schema, generate synthetic examples |
| `GET`  | `/api/connections` | List saved connection aliases |

### Query
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/query` | Full NL→SQL pipeline. Body: `{question, connection_alias, chat_id}` |

### Feedback
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/feedback` | Rate query 1–5. Rating ≥ 4 triggers ChromaDB re-index |

### Chat & Memory
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/chat/list` | Recent chats for sidebar |
| `GET`  | `/api/chat/history/{chat_id}` | Full message history for a session |
| `POST` | `/api/chat/close/{chat_id}` | Archive session to MongoDB + ingest into knowledge graph |
| `POST` | `/api/chat/resume/{chat_id}` | Restore archived session to Redis |
| `GET`  | `/api/chat/search?q=<topic>` | Semantic search across past sessions (knowledge graph) |
| `GET`  | `/api/chat/health` | Health check: Redis, MongoDB, Kuzu |

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| API framework | FastAPI + Uvicorn | 0.115+ / 0.30+ |
| LLM calls | `claude -p` subprocess | No API key required |
| Schema linking | SQLAlchemy FK graph | 2.0+ |
| Few-shot retrieval | ChromaDB | 0.5+ |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 3.0+ |
| Active memory | Redis | 5.0+ |
| Long-term memory | MongoDB | 4.8+ |
| Knowledge graph | Kuzu | 0.6+ |
| Charts | Matplotlib + Pandas | 3.9+ / 2.2+ |
| Frontend | React 18 + TypeScript + Vite | 18.3 / 5.5 / 5.4 |
| State management | Zustand | 4.5+ |

---

## Getting Started

### Prerequisites
- [Claude Code CLI](https://claude.ai/code) installed and authenticated
- Python 3.11+
- Node.js 18+
- Redis (local or Docker)
- MongoDB (local or Docker)

### 1. Clone and install

```bash
git clone https://github.com/Lochan4/vaultsql.git
cd vaultsql

# Backend
pip install -e .

# Frontend
cd frontend && npm install
```

### 2. Start services (optional Docker)

```bash
docker-compose up -d   # starts Redis + MongoDB
```

Or install Redis and MongoDB directly and run them locally.

### 3. Start the API

```bash
uvicorn api.main:app --reload
```

### 4. Start the frontend

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

### 5. Connect a database

Fill in the connection form in the UI (host, port, database, username, password) for your database type. VaultSQL will:
- Test the connection
- Introspect your schema and FK graph
- Generate synthetic example queries to cold-start retrieval

Then start asking questions.

---

## Configuration

### enrichment.yaml

The only file you need to edit. Describes your business context:

```yaml
tables:
  orders:
    description: "customer purchase records"
    synonyms: [transactions, purchases, sales]
    columns:
      status:
        description: "order lifecycle state"
        values: [pending, confirmed, shipped, delivered, cancelled]
      total_amount:
        description: "order value in USD before tax"

glossary:
  revenue:
    aliases: [make, earn, earnings, income, sales]
    sql_pattern: "SUM(orders.total_amount) WHERE orders.status='delivered'"
    maps_to_tables: [orders]

  churn:
    aliases: [lost, churned, inactive]
    sql_pattern: "users WHERE last_active < NOW() - INTERVAL '90 days'"
    maps_to_tables: [users]
```

---

## Research Foundation

VaultSQL's architecture is grounded in recent research:

| Paper | What it contributes |
|-------|-------------------|
| **SchemaGraphSQL** (EACL 2026) | FK pathfinding for schema linking — deterministic, zero-shot, no training |
| **EllieSQL** (2025) | Complexity-aware model routing to reduce cost without sacrificing quality |
| **GRASP** (2025) | Schema pruning: only pass the relevant subgraph to the SQL generator |

---

## Design Principles

1. **Deterministic schema linking** — FK pathfinding, not embedding similarity
2. **Subgraph pruning** — never send the full schema to the LLM
3. **No training required** — zero-shot with few-shot examples from your own queries
4. **Self-hosted only** — no cloud services, no external auth, your data stays local
5. **SELECT-only execution** — no writes, deletes, or DDL from the assistant
6. **Best-effort memory** — graph/memory failures never block a query response

---

## License

MIT — see [LICENSE](LICENSE).
