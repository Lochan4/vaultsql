import { useState } from 'react'
import { connections as connectionsApi, ApiError } from '../lib/api'
import { useConnectionStore } from '../store/connection'
import styles from './DBConnector.module.css'

type DBType = 'postgresql' | 'mysql' | 'sqlite' | 'mssql'

const DB_TYPES: { value: DBType; label: string; placeholder: string }[] = [
  {
    value: 'postgresql',
    label: 'PostgreSQL',
    placeholder: 'postgresql://user:password@host:5432/dbname',
  },
  {
    value: 'mysql',
    label: 'MySQL',
    placeholder: 'mysql+pymysql://user:password@host:3306/dbname',
  },
  {
    value: 'sqlite',
    label: 'SQLite',
    placeholder: 'sqlite:///path/to/database.db',
  },
  {
    value: 'mssql',
    label: 'MS SQL',
    placeholder: 'mssql+pyodbc://user:password@host/dbname?driver=ODBC+Driver+17+for+SQL+Server',
  },
]

type TestState = 'idle' | 'testing' | 'ok' | 'error'

export default function DBConnector() {
  const { setConnection } = useConnectionStore()

  const [dbType, setDbType] = useState<DBType>('postgresql')
  const [connString, setConnString] = useState('')
  const [alias, setAlias] = useState('')
  const [testState, setTestState] = useState<TestState>('idle')
  const [testError, setTestError] = useState('')
  const [saving, setSaving] = useState(false)

  const selectedType = DB_TYPES.find((d) => d.value === dbType)!

  async function handleTest() {
    if (!connString.trim()) return
    setTestState('testing')
    setTestError('')
    try {
      const res = await connectionsApi.test(connString.trim())
      if (res.ok) {
        setTestState('ok')
      } else {
        setTestState('error')
        setTestError(res.error ?? 'Connection failed')
      }
    } catch (err) {
      setTestState('error')
      setTestError(err instanceof ApiError ? err.message : 'Connection failed')
    }
  }

  async function handleSave() {
    if (!connString.trim() || !alias.trim() || testState !== 'ok') return
    setSaving(true)
    try {
      await connectionsApi.save({ alias: alias.trim(), connection_string: connString.trim() })
      setConnection(alias.trim(), dbType)
    } catch (err) {
      setTestState('error')
      setTestError(err instanceof ApiError ? err.message : 'Failed to save connection')
      setSaving(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.logo}>
            Vault<span className={styles.logoAccent}>SQL</span>
          </div>
          <p className={styles.tagline}>Connect your database to get started</p>
        </div>

        {/* DB type selector */}
        <div className={styles.field}>
          <label className={styles.label}>Database type</label>
          <div className={styles.tabs}>
            {DB_TYPES.map((db) => (
              <button
                key={db.value}
                className={`${styles.tab} ${dbType === db.value ? styles.tabActive : ''}`}
                onClick={() => { setDbType(db.value); setTestState('idle') }}
              >
                {db.label}
              </button>
            ))}
          </div>
        </div>

        {/* Connection string */}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="connString">Connection string</label>
          <textarea
            id="connString"
            className={styles.textarea}
            value={connString}
            onChange={(e) => { setConnString(e.target.value); setTestState('idle') }}
            placeholder={selectedType.placeholder}
            rows={2}
            spellCheck={false}
          />
        </div>

        {/* Alias */}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="alias">Connection name</label>
          <input
            id="alias"
            className={styles.input}
            type="text"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="e.g. production-pg"
          />
        </div>

        {/* Test feedback */}
        {testState === 'ok' && (
          <div className={styles.feedbackOk}>
            <CheckIcon /> Connection successful
          </div>
        )}
        {testState === 'error' && (
          <div className={styles.feedbackError}>
            <XIcon /> {testError}
          </div>
        )}

        {/* Actions */}
        <div className={styles.actions}>
          <button
            className={styles.testBtn}
            onClick={handleTest}
            disabled={!connString.trim() || testState === 'testing'}
          >
            {testState === 'testing' ? 'Testing…' : 'Test connection'}
          </button>
          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={testState !== 'ok' || !alias.trim() || saving}
          >
            {saving ? 'Connecting…' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2.5 7l3 3 6-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
