import { useConnectionStore } from './store/connection'
import Sidebar from './components/layout/Sidebar'
import DBConnector from './components/DBConnector'
import Chat from './components/Chat'
import styles from './App.module.css'

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
