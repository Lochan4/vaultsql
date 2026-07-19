import { useEffect, useRef, useState } from 'react'
import { query as queryApi, feedback as feedbackApi, chat as chatApi, ApiError } from '../lib/api'
import type { Message } from '../lib/api'
import { useChatStore } from '../store/chat'
import { useConnectionStore } from '../store/connection'
import TopBar from './layout/TopBar'
import MessageBubble from './MessageBubble'
import styles from './Chat.module.css'

const EXAMPLE_QUESTIONS = [
  'Show me total revenue by month for this year',
  'Who are the top 10 customers by order value?',
  'What is the churn rate over the last 6 months?',
]

const LOADING_STEPS = [
  { key: 'extracting',  label: 'Extracting anchors' },
  { key: 'pathfinding', label: 'Finding join paths' },
  { key: 'generating',  label: 'Generating SQL' },
  { key: 'executing',   label: 'Running query' },
] as const

export default function Chat() {
  const { alias } = useConnectionStore()
  const {
    activeChatId, messages, loadingStep, error,
    addMessage, setMessages, setLoadingStep, setError,
    startNewChat, prependSession,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [lastModel, setLastModel] = useState<string | undefined>()
  const threadRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load messages when active chat changes
  useEffect(() => {
    if (!activeChatId) { startNewChat(); return }
    if (activeChatId.startsWith('chat-')) {
      // Brand new local ID — no messages to load
      setMessages([])
      return
    }
    chatApi.history(activeChatId)
      .then((ctx) => setMessages(ctx.messages))
      .catch(() => {})
  }, [activeChatId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom on new messages
  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loadingStep])

  // Auto-resize textarea
  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  async function handleSubmit(text?: string) {
    const question = (text ?? input).trim()
    if (!question || loadingStep !== null || !alias || !activeChatId) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setError(null)

    // Optimistically add user message
    const userMsg: Message = { role: 'user', content: question }
    addMessage(userMsg)

    // Step through loading pipeline
    const steps: Array<typeof LOADING_STEPS[number]['key']> = [
      'extracting', 'pathfinding', 'generating', 'executing',
    ]
    let stepIdx = 0
    setLoadingStep(steps[stepIdx])

    const stepInterval = setInterval(() => {
      stepIdx = Math.min(stepIdx + 1, steps.length - 1)
      setLoadingStep(steps[stepIdx])
    }, 1800)

    try {
      const res = await queryApi.run({
        question,
        connection_alias: alias,
        chat_id: activeChatId,
      })

      clearInterval(stepInterval)
      setLoadingStep(null)
      setLastModel(res.model_used)

      const assistantMsg: Message = {
        role: 'assistant',
        content: res.explanation,
        metadata: {
          sql: res.sql,
          tables: res.tables_used,
          chart_b64: res.chart_b64,
          chart_type: res.chart_type,
          columns: res.columns,
          rows: res.rows,
          row_count: res.row_count,
          truncated: res.truncated,
          model_used: res.model_used,
        },
      }
      addMessage(assistantMsg)

      // Update sidebar with session summary stub
      prependSession({
        chat_id: activeChatId,
        summary: question,
        db_alias: alias,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })

    } catch (err) {
      clearInterval(stepInterval)
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try rephrasing.')
    }
  }

  async function handleFeedback(msg: Message, rating: number) {
    if (!msg.metadata?.sql || !activeChatId) return
    await feedbackApi.submit({
      chat_id: activeChatId,
      question: messages.find((m) => m.role === 'user')?.content ?? '',
      sql: msg.metadata.sql,
      tables: msg.metadata.tables ?? [],
      rating,
    }).catch(() => {})
  }

  const isEmpty = messages.length === 0 && !loadingStep

  return (
    <div className={styles.container}>
      <TopBar modelUsed={lastModel} />

      <div className={styles.thread} ref={threadRef}>

        {/* Empty state */}
        {isEmpty && (
          <div className={styles.emptyState}>
            <h1 className={styles.emptyTitle}>Ask anything about your data</h1>
            <p className={styles.emptySubtitle}>
              Connected to <strong>{alias}</strong>
            </p>
            <div className={styles.chips}>
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  className={styles.chip}
                  onClick={() => handleSubmit(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages */}
        {messages.map((msg, i) => (
          <div key={i} className={styles.msgRow}>
            <MessageBubble message={msg} />
            {msg.role === 'assistant' && msg.metadata?.sql && (
              <div className={styles.feedbackRow}>
                <span className={styles.feedbackLabel}>Was this helpful?</span>
                {[5, 4, 3, 2, 1].map((r) => (
                  <button
                    key={r}
                    className={styles.feedbackBtn}
                    onClick={() => handleFeedback(msg, r)}
                    aria-label={`Rate ${r} out of 5`}
                  >
                    {r >= 4 ? '👍' : '👎'}
                  </button>
                )).slice(0, 2)}
              </div>
            )}
          </div>
        ))}

        {/* Loading indicator */}
        {loadingStep && (
          <div className={styles.loadingBubble}>
            <div className={styles.loadingSteps}>
              {LOADING_STEPS.map((step) => {
                const stepKeys = LOADING_STEPS.map((s) => s.key)
                const currentIdx = stepKeys.indexOf(loadingStep)
                const thisIdx = stepKeys.indexOf(step.key)
                const done = thisIdx < currentIdx
                const active = step.key === loadingStep
                return (
                  <span
                    key={step.key}
                    className={`${styles.step} ${done ? styles.stepDone : ''} ${active ? styles.stepActive : ''}`}
                  >
                    {done ? '✓ ' : active ? <Pulse /> : '· '}
                    {step.label}
                  </span>
                )
              })}
            </div>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className={styles.errorBubble}>
            <span className={styles.errorText}>{error}</span>
            <span className={styles.errorHint}>Try rephrasing your question.</span>
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className={styles.inputBar}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about your data…"
          rows={1}
          disabled={loadingStep !== null}
        />
        <button
          className={styles.sendBtn}
          onClick={() => handleSubmit()}
          disabled={!input.trim() || loadingStep !== null}
          aria-label="Send"
        >
          <SendIcon />
        </button>
      </div>
    </div>
  )
}

function Pulse() {
  return <span className={styles.pulse}>●</span>
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M14 8L2 2l3 6-3 6 12-6z" fill="currentColor" />
    </svg>
  )
}
