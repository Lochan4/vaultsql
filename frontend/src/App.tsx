import { useConnectionStore } from './store/connection'
import Sidebar from './components/layout/Sidebar'
import styles from './App.module.css'

// Lazy imports — filled in later stages
const DBConnector = () => (
  <div className={styles.placeholder}>
    <p>DB Connector — Stage 5</p>
  </div>
)

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
