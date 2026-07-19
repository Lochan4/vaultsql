/* ─────────────────────────────────────────────────────────────────────────────
   VaultSQL API Client
   Typed wrapper for every FastAPI endpoint.
   All fetch calls go through here — nothing else talks to the network directly.
   Base URL is empty so Vite's proxy (/api → :8000) handles routing.
   ───────────────────────────────────────────────────────────────────────────── */

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Connection {
  alias: string
  connection_string: string
  enrichment_path?: string
}

export interface ConnectionResponse {
  alias: string
  dialect: string
  tables: string[]
  synthetic_examples_added: number
}

export interface QueryRequest {
  question: string
  connection_alias: string
  chat_id: string
  enrichment_path?: string
}

export interface QueryResponse {
  question: string
  sql: string
  explanation: string
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
  chart_type: string
  chart_b64: string
  model_used: string
  tables_used: string[]
  chat_id: string
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  metadata?: {
    sql?: string
    tables?: string[]
    chart_b64?: string
    chart_type?: string
    columns?: string[]
    rows?: Record<string, unknown>[]
    row_count?: number
    truncated?: boolean
    model_used?: string
  }
  created_at?: string
}

export interface ChatSummary {
  chat_id: string
  summary: string
  created_at: string
  updated_at: string
  db_alias: string
}

export interface ChatContext {
  chat_id: string
  summary: string
  messages: Message[]
}

export interface FeedbackRequest {
  chat_id: string
  question: string
  sql: string
  tables: string[]
  rating: number  // 1–5
}

export interface SessionMatch {
  session_id: string
  topic_summary: string
  db_alias: string
  similarity: number
  matched_entities: string[]
}

export interface SearchResponse {
  sessions: SessionMatch[]
  graph_enabled: boolean
}

export interface HealthResponse {
  redis: boolean
  mongodb: boolean
  graph?: boolean
}

// ── Error handling ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }

  return res.json() as Promise<T>
}

// ── Connections ───────────────────────────────────────────────────────────────

export const connections = {
  save: (data: Connection) =>
    request<ConnectionResponse>('/api/connections', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  test: (connection_string: string) =>
    request<{ ok: boolean; dialect: string; error?: string }>(
      '/api/connections/test',
      { method: 'POST', body: JSON.stringify({ connection_string }) }
    ),

  list: () =>
    request<{ connections: string[] }>('/api/connections'),
}

// ── Query ─────────────────────────────────────────────────────────────────────

export const query = {
  run: (data: QueryRequest) =>
    request<QueryResponse>('/api/query', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// ── Feedback ──────────────────────────────────────────────────────────────────

export const feedback = {
  submit: (data: FeedbackRequest) =>
    request<{ status: string }>('/api/feedback', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export const chat = {
  list: () =>
    request<{ chats: ChatSummary[] }>('/api/chat/list'),

  history: (chat_id: string) =>
    request<ChatContext>(`/api/chat/history/${chat_id}`),

  close: (chat_id: string) =>
    request<{ status: string; chat_id: string }>(`/api/chat/close/${chat_id}`, {
      method: 'POST',
    }),

  resume: (chat_id: string) =>
    request<ChatContext>(`/api/chat/resume/${chat_id}`, {
      method: 'POST',
    }),

  search: (q: string, limit = 5) =>
    request<SearchResponse>(`/api/chat/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  health: () =>
    request<HealthResponse>('/api/chat/health'),
}
