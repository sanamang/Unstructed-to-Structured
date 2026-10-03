import {
  blockingIssues,
  formatDate,
  formatMoney,
  formatPercent,
  issueLabel,
  lowConfidenceIssues,
  ruleIssues,
} from '../format'
import Icon from './Icon'

function StatusTag({ doc }) {
  if (doc.status === 'uploaded') return <span className="tag tag-blue">Not structured yet</span>
  if (doc.status === 'unrecognized') return <span className="tag tag-gray">Not an invoice</span>
  if (doc.status === 'accepted') {
    return blockingIssues(doc.validation_issues).length === 0 ? (
      <span className="tag tag-green">Auto-accepted</span>
    ) : (
      <span className="tag tag-green">Reviewed</span>
    )
  }
  const rules = ruleIssues(doc.validation_issues)
  if (rules.length > 0) {
    return (
      <span className="tag tag-red">
        {issueLabel(rules[0])}
        {rules.length > 1 && ` +${rules.length - 1}`}
      </span>
    )
  }
  const low = lowConfidenceIssues(doc.validation_issues).length
  return (
    <span className="tag tag-amber">
      Low confidence ({low} field{low === 1 ? '' : 's'})
    </span>
  )
}

export default function DocumentList({
  tabs,
  status,
  onStatusChange,
  query,
  onQueryChange,
  documents,
  loading,
  selectedId,
  onSelect,
}) {
  return (
    <section className="queue">
      <div className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            className={status === tab.value ? 'active' : ''}
            onClick={() => onStatusChange(tab.value)}
          >
            {tab.label}
            {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
          </button>
        ))}
      </div>

      <label className="search">
        <Icon name="search" size={16} />
        <input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter vendor, invoice #, amount…"
        />
        {query && (
          <button className="icon-button" onClick={() => onQueryChange('')} aria-label="Clear filter">
            <Icon name="x" size={14} />
          </button>
        )}
      </label>

      <ul className="cards">
        {loading && <li className="queue-empty">Loading…</li>}
        {!loading && documents.length === 0 && (
          <li className="queue-empty">{query ? 'No documents match this filter.' : 'Nothing here.'}</li>
        )}
        {documents.map((doc) => {
          const isInvoice = doc.doc_type === 'invoice'
          const isUploaded = doc.status === 'uploaded'
          const confidence = isInvoice ? doc.min_confidence : doc.classification_confidence
          const subtitle = isInvoice
            ? doc.invoice_number || 'No invoice #'
            : isUploaded
              ? doc.source_filename
              : 'Unrecognized document'
          return (
            <li key={doc.id}>
              <button
                className={`doc-card ${doc.id === selectedId ? 'selected' : ''}`}
                onClick={() => onSelect(doc.id)}
              >
                <div className="card-row">
                  <span className="card-title">
                    {doc.vendor_name || (isUploaded ? 'New upload' : doc.source_filename)}
                  </span>
                  <span className="card-amount mono">{formatMoney(doc.total_due, doc.currency)}</span>
                </div>
                <div className="card-row card-sub">
                  <span className={isInvoice || isUploaded ? 'mono' : ''}>{subtitle}</span>
                  <span>{formatDate(doc.invoice_date || doc.created_at)}</span>
                </div>
                <div className="card-row">
                  <StatusTag doc={doc} />
                  {!isUploaded && (
                    <span
                      className="card-confidence mono"
                      title={isInvoice ? 'Lowest field confidence' : 'Classification confidence'}
                    >
                      <Icon name="sparkles" size={12} /> {formatPercent(confidence)} conf
                    </span>
                  )}
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
