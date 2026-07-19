import styles from './ChartView.module.css'

interface ChartViewProps {
  chartB64: string
  chartType: string
}

export default function ChartView({ chartB64, chartType }: ChartViewProps) {
  if (!chartB64) return null

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <span className={styles.label}>{chartType || 'Chart'}</span>
      </div>
      <div className={styles.imgWrap}>
        <img
          src={`data:image/png;base64,${chartB64}`}
          alt={`${chartType} chart`}
          className={styles.img}
        />
      </div>
    </div>
  )
}
