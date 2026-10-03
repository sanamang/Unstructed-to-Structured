import { CONFIDENCE_THRESHOLD } from '../format'

export default function ConfidenceBadge({ confidence, page }) {
  if (confidence === undefined || confidence === null) return null
  const low = confidence < CONFIDENCE_THRESHOLD
  return (
    <span className={`confidence-badge ${low ? 'low' : 'high'}`} title={page ? `Read from page ${page}` : undefined}>
      {(confidence * 100).toFixed(0)}%
    </span>
  )
}
