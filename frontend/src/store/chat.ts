import { create } from 'zustand'
import type { Message, ChatSummary } from '../lib/api'

export type LoadingStep =
  | 'extracting'
  | 'pathfinding'
  | 'generating'
  | 'executing'
  | null

interface ChatState {
  // Session list (sidebar)
  sessions: ChatSummary[]
  activeChatId: string | null

  // Messages for the active session
  messages: Message[]

  // Loading pipeline step
  loadingStep: LoadingStep

  // Error for last query
  error: string | null

  // Actions
  setSessions: (sessions: ChatSummary[]) => void
  setActiveChat: (chat_id: string) => void
  startNewChat: () => void
  addMessage: (msg: Message) => void
  setMessages: (msgs: Message[]) => void
  setLoadingStep: (step: LoadingStep) => void
  setError: (err: string | null) => void
  prependSession: (session: ChatSummary) => void
}

function newChatId(): string {
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeChatId: null,
  messages: [],
  loadingStep: null,
  error: null,

  setSessions: (sessions) => set({ sessions }),

  setActiveChat: (chat_id) =>
    set({ activeChatId: chat_id, messages: [], error: null }),

  startNewChat: () =>
    set({
      activeChatId: newChatId(),
      messages: [],
      loadingStep: null,
      error: null,
    }),

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  setMessages: (msgs) => set({ messages: msgs }),

  setLoadingStep: (step) => set({ loadingStep: step }),

  setError: (err) => set({ error: err, loadingStep: null }),

  prependSession: (session) =>
    set((state) => ({
      sessions: [session, ...state.sessions.filter((s) => s.chat_id !== session.chat_id)],
    })),
}))

export { newChatId }
