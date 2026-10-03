export const CONFIDENCE_THRESHOLD = 0.75

export function formatMoney(amount, currency) {
  if (amount === null || amount === undefined) return '—'
  if (!currency) return amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

// Date-only ISO strings ("2026-09-01") are parsed as local dates so they
// don't shift a day in timezones behind UTC.
export function formatDate(value) {
  if (!value) return '—'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.exec(value)
  const date = dateOnly
    ? new Date(Number(value.slice(0, 4)), Number(value.slice(5, 7)) - 1, Number(value.slice(8, 10)))
    : new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatPercent(value, digits = 0) {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

const RULE_LABELS = {
  required_field_missing: 'Missing field',
  line_items_sum_mismatch: 'Line items ≠ subtotal',
  totals_mismatch: 'Totals don’t add up',
  due_date_not_after_invoice_date: 'Due date before invoice date',
  invalid_date_format: 'Unreadable date',
  low_confidence_field: 'Low confidence',
  optional_field_missing: 'Not on document',
  value_filled_in: 'Filled in',
}

export function humanizeField(field) {
  return (field || '').replace(/_/g, ' ')
}

export function issueLabel(issue) {
  if (issue.rule === 'required_field_missing' && issue.field) return `Missing ${humanizeField(issue.field)}`
  return RULE_LABELS[issue.rule] || humanizeField(issue.rule)
}

// Issues with severity "info" are notes (a field that isn't on the document,
// a value filled in from the others) and never block auto-accept.
const isInfo = (i) => i.severity === 'info'

export function ruleIssues(issues) {
  return (issues || []).filter((i) => !isInfo(i) && i.rule !== 'low_confidence_field')
}

export function lowConfidenceIssues(issues) {
  return (issues || []).filter((i) => !isInfo(i) && i.rule === 'low_confidence_field')
}

export function infoIssues(issues) {
  return (issues || []).filter(isInfo)
}

export function blockingIssues(issues) {
  return (issues || []).filter((i) => !isInfo(i))
}
