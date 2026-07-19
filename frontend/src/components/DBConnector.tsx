import { useState } from 'react'
import { connections as connectionsApi, ApiError } from '../lib/api'
import { useConnectionStore } from '../store/connection'
import styles from './DBConnector.module.css'

// ── DB type definitions ───────────────────────────────────────────────────────

type DBType = 'postgresql' | 'mysql' | 'sqlite' | 'mssql'

interface FieldDef {
  key: string
  label: string
  placeholder: string
  type: 'text' | 'password' | 'number'
  defaultValue?: string
}

const DB_CONFIG: Record<DBType, { label: string; fields: FieldDef[] }> = {
  postgresql: {
    label: 'PostgreSQL',
    fields: [
      { key: 'host',     label: 'Host',     placeholder: 'localhost',   type: 'text' },
      { key: 'port',     label: 'Port',     placeholder: '5432',        type: 'number', defaultValue: '5432' },
      { key: 'database', label: 'Database', placeholder: 'mydb',        type: 'text' },
      { key: 'username', label: 'Username', placeholder: 'postgres',    type: 'text' },
      { key: 'password', label: 'Password', placeholder: '••••••••',    type: 'password' },
    ],
  },
  mysql: {
    label: 'MySQL',
    fields: [
      { key: 'host',     label: 'Host',     placeholder: 'localhost',   type: 'text' },
      { key: 'port',     label: 'Port',     placeholder: '3306',        type: 'number', defaultValue: '3306' },
      { key: 'database', label: 'Database', placeholder: 'mydb',        type: 'text' },
      { key: 'username', label: 'Username', placeholder: 'root',        type: 'text' },
      { key: 'password', label: 'Password', placeholder: '••••••••',    type: 'password' },
    ],
  },
  mssql: {
    label: 'MS SQL',
    fields: [
      { key: 'host',     label: 'Host',     placeholder: 'localhost',   type: 'text' },
      { key: 'database', label: 'Database', placeholder: 'mydb',        type: 'text' },
      { key: 'username', label: 'Username', placeholder: 'sa',          type: 'text' },
      { key: 'password', label: 'Password', placeholder: '••••••••',    type: 'password' },
    ],
  },
  sqlite: {
    label: 'SQLite',
    fields: [
      { key: 'path', label: 'File path', placeholder: './data/mydb.db', type: 'text' },
    ],
  },
}

// ── Connection string builders ────────────────────────────────────────────────

function buildConnectionString(type: DBType, fields: Record<string, string>): string {
  const { host, port, database, username, password, path } = fields
  switch (type) {
    case 'postgresql':
      return `postgresql://${username}:${password}@${host}:${port || '5432'}/${database}`
    case 'mysql':
      return `mysql+pymysql://${username}:${password}@${host}:${port || '3306'}/${database}`
    case 'mssql':
      return `mssql+pyodbc://${username}:${password}@${host}/${database}?driver=ODBC+Driver+17+for+SQL+Server`
    case 'sqlite':
      return `sqlite:///${path}`
  }
}

function isFormComplete(type: DBType, fields: Record<string, string>): boolean {
  return DB_CONFIG[type].fields.every((f) => fields[f.key]?.trim())
}

// ── Types ─────────────────────────────────────────────────────────────────────

type TestState = 'idle' | 'testing' | 'ok' | 'error'
type SaveState = 'idle' | 'saving' | 'done'

interface SuccessInfo {
  tables: number
  examples: number
  dialect: string
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DBConnector() {
  const { setConnection } = useConnectionStore()

  const [dbType, setDbType]         = useState<DBType>('postgresql')
  const [fields, setFields]         = useState<Record<string, string>>({})
  const [alias, setAlias]           = useState('')
  const [testState, setTestState]   = useState<TestState>('idle')
  const [testError, setTestError]   = useState('')
  const [saveState, setSaveState]   = useState<SaveState>('idle')
  const [successInfo, setSuccessInfo] = useState<SuccessInfo | null>(null)

  function handleTypeChange(type: DBType) {
    setDbType(type)
    // Seed defaults (e.g. port)
    const defaults: Record<string, string> = {}
    DB_CONFIG[type].fields.forEach((f) => {
      if (f.defaultValue) defaults[f.key] = f.defaultValue
    })
    setFields(defaults)
    setTestState('idle')
    setTestError('')
  }

  function handleField(key: string, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }))
    setTestState('idle')
  }

  async function handleTest() {
    if (!isFormComplete(dbType, fields)) return
    setTestState('testing')
    setTestError('')
    try {
      const connStr = buildConnectionString(dbType, fields)
      const res = await connectionsApi.test(connStr)
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

  async function handleConnect() {
    if (testState !== 'ok' || !alias.trim()) return
    setSaveState('saving')
    try {
      const connStr = buildConnectionString(dbType, fields)
      const res = await connectionsApi.save({
        alias: alias.trim(),
        connection_string: connStr,
      })
      setSuccessInfo({
        tables:   res.tables.length,
        examples: res.synthetic_examples_added,
        dialect:  res.dialect,
      })
      setSaveState('done')
      // Transition to chat after brief success display
      setTimeout(() => setConnection(alias.trim(), res.dialect), 1800)
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Failed to connect')
      setTestState('error')
      setSaveState('idle')
    }
  }

  const config   = DB_CONFIG[dbType]
  const complete = isFormComplete(dbType, fields)

  // Two-column layout for host+port fields
  function renderFields() {
    const fieldDefs = config.fields
    const result: React.ReactNode[] = []
    let i = 0
    while (i < fieldDefs.length) {
      const f = fieldDefs[i]
      const next = fieldDefs[i + 1]
      // Pair host+port side by side
      if (f.key === 'host' && next?.key === 'port') {
        result.push(
          <div key="host-port" className={styles.fieldRow}>
            <div className={styles.field} style={{ flex: 3 }}>
              <label className={styles.label} htmlFor="host">{f.label}</label>
              <input
                id="host"
                className={styles.input}
                type="text"
                value={fields['host'] ?? ''}
                onChange={(e) => handleField('host', e.target.value)}
                placeholder={f.placeholder}
                autoComplete="off"
              />
            </div>
            <div className={styles.field} style={{ flex: 1 }}>
              <label className={styles.label} htmlFor="port">{next.label}</label>
              <input
                id="port"
                className={styles.input}
                type="number"
                value={fields['port'] ?? next.defaultValue ?? ''}
                onChange={(e) => handleField('port', e.target.value)}
                placeholder={next.placeholder}
              />
            </div>
          </div>
        )
        i += 2
        continue
      }

      result.push(
        <div key={f.key} className={styles.field}>
          <label className={styles.label} htmlFor={f.key}>{f.label}</label>
          <input
            id={f.key}
            className={styles.input}
            type={f.type}
            value={fields[f.key] ?? ''}
            onChange={(e) => handleField(f.key, e.target.value)}
            placeholder={f.placeholder}
            autoComplete={f.type === 'password' ? 'current-password' : 'off'}
          />
        </div>
      )
      i++
    }
    return result
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>

        <div className={styles.cardHeader}>
          <div className={styles.logo}>Vault<span className={styles.logoAccent}>SQL</span></div>
          <p className={styles.tagline}>Connect your database to get started</p>
        </div>

        {/* DB type tabs */}
        <div className={styles.field}>
          <label className={styles.label}>Database type</label>
          <div className={styles.tabs}>
            {(Object.keys(DB_CONFIG) as DBType[]).map((type) => (
              <button
                key={type}
                className={`${styles.tab} ${dbType === type ? styles.tabActive : ''}`}
                onClick={() => handleTypeChange(type)}
              >
                {DB_CONFIG[type].label}
              </button>
            ))}
          </div>
        </div>

        {/* Per-DB fields */}
        {renderFields()}

        {/* Connection name */}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="alias">Connection name</label>
          <input
            id="alias"
            className={styles.input}
            type="text"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder={`e.g. production-${dbType === 'postgresql' ? 'pg' : dbType}`}
            autoComplete="off"
          />
        </div>

        {/* Feedback */}
        {testState === 'ok' && saveState === 'idle' && (
          <div className={styles.feedbackOk}>
            <CheckIcon /> Connection successful
          </div>
        )}
        {testState === 'error' && (
          <div className={styles.feedbackError}>
            <XIcon /> {testError}
          </div>
        )}
        {saveState === 'done' && successInfo && (
          <div className={styles.feedbackOk}>
            <CheckIcon />
            Connected — found <strong>{successInfo.tables}</strong> tables,
            generated <strong>{successInfo.examples}</strong> examples
          </div>
        )}

        {/* Actions */}
        <div className={styles.actions}>
          <button
            className={styles.testBtn}
            onClick={handleTest}
            disabled={!complete || testState === 'testing' || saveState !== 'idle'}
          >
            {testState === 'testing' ? 'Testing…' : 'Test connection'}
          </button>
          <button
            className={styles.saveBtn}
            onClick={handleConnect}
            disabled={testState !== 'ok' || !alias.trim() || saveState !== 'idle'}
          >
            {saveState === 'saving' ? 'Connecting…' : saveState === 'done' ? 'Connected ✓' : 'Connect'}
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
