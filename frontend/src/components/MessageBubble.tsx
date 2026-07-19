import type { Message } from '../lib/api'
import SQLBlock from './SQLBlock'
import ResultTable from './ResultTable'
import ChartView from './ChartView'
import styles from './MessageBubble.module.css'

interface MessageBubbleProps {
  message: Message
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const meta = message.metadata

  return (
    <div className={`${styles.bubble} ${isUser ? styles.user : styles.assistant}`}>
      <span className={styles.roleMeta}>{isUser ? 'You' : 'VaultSQL'}</span>

      {/* Message text */}
      <p className={styles.text}>{message.content}</p>

      {/* SQL block — assistant only */}
      {!isUser && meta?.sql && <SQLBlock sql={meta.sql} />}

      {/* Result table — assistant only */}
      {!isUser && meta?.columns && meta?.rows && (
        <ResultTable
          columns={meta.columns}
          rows={meta.rows}
          rowCount={meta.row_count ?? meta.rows.length}
          truncated={meta.truncated ?? false}
        />
      )}

      {/* Chart — assistant only */}
      {!isUser && meta?.chart_b64 && (
        <ChartView chartB64={meta.chart_b64} chartType={meta.chart_type ?? ''} />
      )}

      {/* Model used — subtle footer */}
      {!isUser && meta?.model_used && (
        <span className={styles.modelTag}>{meta.model_used}</span>
      )}
    </div>
  )
}
