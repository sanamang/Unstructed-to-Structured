const THRESHOLD = 0.75

export default function ConfidenceBadge({ confidence, page }) {
  if (confidence === undefined || confidence === null) return null
  const low = confidence < THRESHOLD
  return (
    <span className={`confidence-badge ${low ? 'low' : 'high'}`} title={page ? `Read from page ${page}` : undefined}>
      {(confidence * 100).toFixed(0)}%
    </span>
  )
}
