import { useState } from 'react'
import styles from './ResultTable.module.css'

interface ResultTableProps {
  columns: string[]
  rows: Record<string, unknown>[]
  rowCount: number
  truncated: boolean
}

const PAGE_SIZE = 50

function isNumeric(value: unknown): boolean {
  return typeof value === 'number' || (typeof value === 'string' && !isNaN(Number(value)) && value.trim() !== '')
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

export default function ResultTable({ columns, rows, rowCount, truncated }: ResultTableProps) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? rows : rows.slice(0, PAGE_SIZE)

  // Detect numeric columns from first few rows
  const numericCols = new Set(
    columns.filter((col) =>
      rows.slice(0, 5).every((row) => isNumeric(row[col]))
    )
  )

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <span className={styles.label}>Results</span>
        <span className={styles.count}>
          {rowCount.toLocaleString()} {rowCount === 1 ? 'row' : 'rows'}
          {truncated && ' (truncated)'}
        </span>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col} className={numericCols.has(col) ? styles.thNum : styles.th}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i} className={styles.row}>
                {columns.map((col) => (
                  <td key={col} className={numericCols.has(col) ? styles.tdNum : styles.td}>
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > PAGE_SIZE && !expanded && (
        <button className={styles.expandBtn} onClick={() => setExpanded(true)}>
          Show all {rows.length.toLocaleString()} rows
        </button>
      )}
    </div>
  )
}
