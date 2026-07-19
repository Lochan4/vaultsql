import { useState } from 'react'
import styles from './SQLBlock.module.css'

interface SQLBlockProps {
  sql: string
}

export default function SQLBlock({ sql }: SQLBlockProps) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={styles.block}>
      <div className={styles.header}>
        <span className={styles.lang}>SQL</span>
        <button className={styles.copyBtn} onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className={styles.code}>
        <code dangerouslySetInnerHTML={{ __html: highlight(sql) }} />
      </pre>
    </div>
  )
}

// Minimal SQL syntax highlighter — keywords, strings, comments
function highlight(sql: string): string {
  const keywords = [
    'SELECT','FROM','WHERE','JOIN','LEFT','RIGHT','INNER','OUTER','FULL',
    'ON','GROUP BY','ORDER BY','HAVING','LIMIT','OFFSET','INSERT','INTO',
    'VALUES','UPDATE','SET','DELETE','CREATE','DROP','ALTER','TABLE',
    'INDEX','VIEW','AS','AND','OR','NOT','IN','IS','NULL','LIKE','BETWEEN',
    'CASE','WHEN','THEN','ELSE','END','DISTINCT','COUNT','SUM','AVG',
    'MIN','MAX','WITH','UNION','ALL','EXISTS','BY','ASC','DESC',
  ]

  // Escape HTML first
  let out = sql
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Comments
  out = out.replace(/(--[^\n]*)/g, '<span class="sql-comment">$1</span>')

  // Strings
  out = out.replace(/('(?:[^'\\]|\\.)*')/g, '<span class="sql-string">$1</span>')

  // Keywords (word-boundary match, case-insensitive)
  const kwPattern = new RegExp(`\\b(${keywords.join('|')})\\b`, 'gi')
  out = out.replace(kwPattern, '<span class="sql-keyword">$1</span>')

  return out
}
