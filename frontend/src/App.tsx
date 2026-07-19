import { useConnectionStore } from './store/connection'
import Sidebar from './components/layout/Sidebar'
import DBConnector from './components/DBConnector'
import styles from './App.module.css'

// Placeholder — replaced in Stage 7
const Chat = () => (
  <div className={styles.placeholder}>
    <p>Chat — Stage 7</p>
  </div>
)

export default function App() {
  const { isConnected } = useConnectionStore()

  if (!isConnected) {
    return <DBConnector />
  }

  return (
    <div className={styles.layout}>
      <Sidebar />
      <div className={styles.main}>
        <Chat />
      </div>
    </div>
  )
}
