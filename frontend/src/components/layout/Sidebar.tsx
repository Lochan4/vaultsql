import { useEffect } from 'react'
import { useChatStore } from '../../store/chat'
import { useConnectionStore } from '../../store/connection'
import { chat as chatApi } from '../../lib/api'
import styles from './Sidebar.module.css'

export default function Sidebar() {
  const { sessions, activeChatId, setSessions, setActiveChat, startNewChat } =
    useChatStore()
  const { alias } = useConnectionStore()

  useEffect(() => {
    chatApi.list().then((res) => setSessions(res.chats)).catch(() => {})
  }, [setSessions])

  return (
    <aside className={styles.sidebar}>
      <div className={styles.header}>
        <div className={styles.logo}>
          Vault<span className={styles.logoAccent}>SQL</span>
        </div>
        {alias && (
          <div className={styles.dbBadge}>
            <span className={styles.dbDot} />
            {alias}
          </div>
        )}
      </div>

      <div className={styles.sectionLabel}>Recent</div>

      <nav className={styles.chatList}>
        {sessions.length === 0 && (
          <p className={styles.empty}>No chats yet</p>
        )}
        {sessions.map((session) => (
          <button
            key={session.chat_id}
            className={`${styles.chatItem} ${activeChatId === session.chat_id ? styles.active : ''}`}
            onClick={() => setActiveChat(session.chat_id)}
          >
            <span className={styles.chatTitle}>
              {session.summary
                ? session.summary.slice(0, 42) + (session.summary.length > 42 ? '…' : '')
                : 'New chat'}
            </span>
            <span className={styles.chatMeta}>
              {session.updated_at
                ? new Date(session.updated_at).toLocaleDateString()
                : ''}
            </span>
          </button>
        ))}
      </nav>

      <button className={styles.newChatBtn} onClick={startNewChat}>
        <PlusIcon />
        New chat
      </button>
    </aside>
  )
}

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
