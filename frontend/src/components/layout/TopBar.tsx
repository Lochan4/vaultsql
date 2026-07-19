import { useConnectionStore } from '../../store/connection'
import styles from './TopBar.module.css'

interface TopBarProps {
  modelUsed?: string
}

export default function TopBar({ modelUsed }: TopBarProps) {
  const { alias, dialect } = useConnectionStore()

  return (
    <header className={styles.topbar}>
      <span className={styles.label}>Connected to</span>
      <span className={styles.chip}>{alias ?? '—'}</span>
      {dialect && <span className={styles.dialectChip}>{dialect}</span>}

      {modelUsed && (
        <>
          <span className={styles.label} style={{ marginLeft: 'auto' }}>Model</span>
          <span className={styles.modelChip}>{modelUsed}</span>
        </>
      )}
    </header>
  )
}
