import { useState } from 'react'
import {
  CONFIDENCE_THRESHOLD,
  formatDate,
  formatMoney,
  formatPercent,
  humanizeField,
  infoIssues,
  issueLabel,
  lowConfidenceIssues,
  ruleIssues,
} from '../format'
import ConfidenceBadge from './ConfidenceBadge'
import Icon from './Icon'

const SCALAR_FIELDS = [
  ['vendor_name', 'Vendor', 'wide'],
  ['invoice_number', 'Invoice #'],
  ['currency', 'Currency'],
  ['invoice_date', 'Invoice date'],
  ['due_date', 'Due date'],
]

const AMOUNT_FIELDS = [
  ['subtotal', 'Subtotal'],
  ['tax', 'Tax'],
  ['total_due', 'Total due'],
]

const NUMERIC_FIELDS = new Set(['subtotal', 'tax', 'total_due', 'quantity', 'unit_price', 'line_total'])
const AMOUNT_TOLERANCE = 0.02

function initialFields(document) {
  if (!document || document.doc_type !== 'invoice') return null
  return {
    vendor_name: document.vendor_name,
    invoice_number: document.invoice_number,
    invoice_date: document.invoice_date,
    due_date: document.due_date,
    currency: document.currency,
    subtotal: document.subtotal,
    tax: document.tax,
    total_due: document.total_due,
    line_items: document.line_items.map((li) => ({ ...li })),
    // Read-only: shown and exported, not edited.
    additional_fields: (document.additional_fields || []).map((f) => ({ ...f })),
  }
}

function emptyLineItem() {
  return { description: '', quantity: 0, unit_price: 0, line_total: 0 }
}

// A field the model reported as not on the document (value null) has no
// meaningful confidence - it's shown as absent (or "filled in" when a value
// was derived from the other amounts) instead of as a red low score.
function readMeta(meta, name) {
  const m = meta[name]
  if (!m) return { confidence: undefined, page: undefined, absent: false }
  return { confidence: m.confidence, page: m.page, absent: m.value === null || m.value === undefined }
}

function AbsentTag({ filled }) {
  return filled ? (
    <span className="absent-tag filled" title="Not on the document; calculated from the other amounts">
      filled in
    </span>
  ) : (
    <span className="absent-tag" title="Not on the document">
      not on doc
    </span>
  )
}

function StatusBadge({ status }) {
  const labels = {
    uploaded: 'Not structured',
    pending_review: 'Requires review',
    accepted: 'Accepted',
    unrecognized: 'Unrecognized',
  }
  return <span className={`status-badge status-${status}`}>{labels[status] || status}</span>
}

function IssueBanner({ issues }) {
  const rules = ruleIssues(issues)
  const lowConfidence = lowConfidenceIssues(issues)
  const notes = infoIssues(issues)
  if (rules.length === 0 && lowConfidence.length === 0 && notes.length === 0) return null
  return (
    <>
      {rules.length > 0 && (
        <div className="banner banner-red">
          <Icon name="alert" size={20} />
          <div>
            <h3>
              {rules.length === 1
                ? `${issueLabel(rules[0])} flagged`
                : `${rules.length} business-rule exceptions flagged`}
            </h3>
            <ul>
              {rules.map((issue, i) => (
                <li key={i}>
                  {rules.length > 1 && <strong>{issueLabel(issue)}: </strong>}
                  {issue.message}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {lowConfidence.length > 0 && (
        <div className="banner banner-amber">
          <Icon name="info" size={20} />
          <div>
            <h3>
              {lowConfidence.length} field{lowConfidence.length === 1 ? '' : 's'} below{' '}
              {formatPercent(CONFIDENCE_THRESHOLD)} extraction confidence
            </h3>
            <div className="chip-list">
              {lowConfidence.map((issue, i) => (
                <span key={i} className="chip mono">
                  {humanizeField(issue.field)}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      {notes.length > 0 && (
        <div className="banner banner-gray">
          <Icon name="info" size={20} />
          <div>
            <h3>
              Structured with {notes.length} gap{notes.length === 1 ? '' : 's'} handled automatically
            </h3>
            <ul>
              {notes.map((issue, i) => (
                <li key={i}>{issue.message}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  )
}

function PageViewer({ document }) {
  const [pageIndex, setPageIndex] = useState(0)
  const count = document.page_urls.length
  const url = document.page_urls[pageIndex]
  return (
    <section className="card page-viewer">
      <header className="card-header">
        <span className="file-name">
          <Icon name="file-text" size={14} />
          {document.source_filename}
        </span>
        <span className="page-controls">
          <button
            className="icon-button"
            disabled={pageIndex === 0}
            onClick={() => setPageIndex((i) => i - 1)}
            aria-label="Previous page"
          >
            <Icon name="chevron-left" size={14} />
          </button>
          <span className="page-chip">
            Page {pageIndex + 1} of {count}
          </span>
          <button
            className="icon-button"
            disabled={pageIndex >= count - 1}
            onClick={() => setPageIndex((i) => i + 1)}
            aria-label="Next page"
          >
            <Icon name="chevron-right" size={14} />
          </button>
        </span>
      </header>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" title="Open full-size page in a new tab">
          <img src={url} alt={`Page ${pageIndex + 1}`} />
        </a>
      ) : (
        <p className="muted">No page image available.</p>
      )}
    </section>
  )
}

function StructurePlaceholder({ structuring, onStructure }) {
  return (
    <section className={`card structure-placeholder ${structuring ? 'working' : ''}`}>
      {structuring ? (
        <>
          <div className="spinner" />
          <h3>Structuring…</h3>
          <p>
            Classifying the document, extracting every field with Claude vision, then checking it against the business
            rules. This usually takes 10–30 seconds.
          </p>
          <div className="skeleton">
            {[70, 45, 85, 60, 90, 50].map((w, i) => (
              <span key={i} style={{ width: `${w}%` }} />
            ))}
          </div>
        </>
      ) : (
        <>
          <Icon name="sparkles" size={28} />
          <h3>Structured data will appear here</h3>
          <p>Press Structure to turn this document into vendor, dates, line items and totals.</p>
          <button className="button primary" onClick={onStructure}>
            <Icon name="sparkles" size={16} /> Structure
          </button>
        </>
      )}
    </section>
  )
}

function JsonView({ fields }) {
  const [copied, setCopied] = useState(false)
  const json = JSON.stringify(fields, null, 2)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable (e.g. insecure context) - nothing to do */
    }
  }
  return (
    <div className="json-view">
      <button className="button secondary copy-button" onClick={copy}>
        {copied ? 'Copied' : 'Copy JSON'}
      </button>
      <pre className="mono">{json}</pre>
    </div>
  )
}

export default function DocumentDetail({ document, onSave, saving, onStructure, structuring }) {
  // The parent keys this component by document id + status + resolution
  // time, so local edits reset whenever a different (or re-saved or newly
  // structured) document loads.
  const [fields, setFields] = useState(() => initialFields(document))
  const [view, setView] = useState('form')

  if (!document) {
    return (
      <main className="detail detail-empty">
        <Icon name="file-text" size={32} />
        <p>Select a document from the queue, or drop any invoice, receipt, photo or email anywhere to upload it.</p>
      </main>
    )
  }

  const meta = document.field_meta || {}
  const dirty = fields && JSON.stringify(fields) !== JSON.stringify(initialFields(document))

  const updateField = (name, rawValue) => {
    const value = NUMERIC_FIELDS.has(name) ? (rawValue === '' ? null : Number(rawValue)) : rawValue || null
    setFields((f) => ({ ...f, [name]: value }))
  }
  const updateLineItem = (index, name, rawValue) => {
    const value = NUMERIC_FIELDS.has(name) ? Number(rawValue) : rawValue
    setFields((f) => ({
      ...f,
      line_items: f.line_items.map((li, i) => (i === index ? { ...li, [name]: value } : li)),
    }))
  }
  const addLineItem = () => setFields((f) => ({ ...f, line_items: [...f.line_items, emptyLineItem()] }))
  const removeLineItem = (index) => setFields((f) => ({ ...f, line_items: f.line_items.filter((_, i) => i !== index) }))

  const title = document.invoice_number
    ? `${document.invoice_number} — ${document.vendor_name || 'Unknown vendor'}`
    : document.vendor_name || document.source_filename
  const isInvoice = document.doc_type === 'invoice'
  const isUploaded = document.status === 'uploaded'

  // Unrecognized documents have no fields, and any amount may be null.
  const isAmount = (v) => typeof v === 'number' && !Number.isNaN(v)
  const lineSum = fields ? fields.line_items.reduce((sum, li) => sum + (Number(li.line_total) || 0), 0) : 0
  const subtotalMatches = isAmount(fields?.subtotal) && Math.abs(lineSum - fields.subtotal) <= AMOUNT_TOLERANCE
  const totalMatches =
    isAmount(fields?.subtotal) &&
    isAmount(fields?.tax) &&
    isAmount(fields?.total_due) &&
    Math.abs(fields.subtotal + fields.tax - fields.total_due) <= AMOUNT_TOLERANCE

  return (
    <main className="detail">
      <section className="card detail-header">
        <div className="detail-title">
          <h2 className={document.invoice_number ? 'mono-title' : ''}>{title}</h2>
          <StatusBadge status={document.status} />
        </div>
        <div className="detail-meta">
          <span>
            {isUploaded ? 'Uploaded' : 'Created'} {formatDate(document.created_at)}
          </span>
          <span className="dot-sep">•</span>
          {isUploaded ? (
            <span>
              {document.page_count} page{document.page_count === 1 ? '' : 's'}
            </span>
          ) : (
            <span>
              <Icon name="sparkles" size={13} /> {isInvoice ? 'Lowest field confidence' : 'Classification confidence'}:{' '}
              <strong className="mono">
                {formatPercent(isInvoice ? document.min_confidence : document.classification_confidence, 1)}
              </strong>
            </span>
          )}
          {document.document_kind && (
            <>
              <span className="dot-sep">•</span>
              <span className="doc-kind">{document.document_kind}</span>
            </>
          )}
          {document.resolved_at && (
            <>
              <span className="dot-sep">•</span>
              <span>Resolved {formatDate(document.resolved_at)}</span>
            </>
          )}
        </div>
        {isUploaded && (
          <div className="detail-actions">
            <button className="button primary structure-button" disabled={structuring} onClick={onStructure}>
              <Icon name="sparkles" size={16} />
              {structuring ? 'Structuring…' : 'Structure'}
            </button>
          </div>
        )}
        {fields && (
          <div className="detail-actions">
            <button
              className="button secondary"
              disabled={!dirty || saving}
              onClick={() => setFields(initialFields(document))}
            >
              <Icon name="undo" size={16} /> Discard edits
            </button>
            <button className="button primary" disabled={saving} onClick={() => onSave(document.id, fields)}>
              <Icon name="check-check" size={16} />
              {saving ? 'Saving…' : document.status === 'accepted' ? 'Save corrections' : 'Approve & accept'}
            </button>
          </div>
        )}
      </section>

      {isUploaded ? (
        <div className="banner banner-blue">
          <Icon name="info" size={20} />
          <div>
            <h3>Uploaded, not structured yet</h3>
            <p>The original is stored below exactly as uploaded. Press Structure to extract its data.</p>
          </div>
        </div>
      ) : isInvoice ? (
        <IssueBanner issues={document.validation_issues} />
      ) : (
        <div className="banner banner-gray">
          <Icon name="file-x" size={20} />
          <div>
            <h3>Not recognized as an invoice</h3>
            <p>
              The classifier was {formatPercent(document.classification_confidence)} confident this document has no
              charges on it (not an invoice, receipt or bill), so no fields were extracted.
            </p>
          </div>
        </div>
      )}

      <div className="detail-body">
        <PageViewer key={document.id} document={document} />

        {isUploaded && <StructurePlaceholder structuring={structuring} onStructure={onStructure} />}

        {fields && (
          <section className="card fields-card">
            <header className="card-header">
              <h3>Structured data</h3>
              <div className="segmented" role="tablist">
                {['form', 'json'].map((v) => (
                  <button key={v} className={view === v ? 'active' : ''} onClick={() => setView(v)}>
                    {v === 'form' ? 'Form' : 'JSON'}
                  </button>
                ))}
              </div>
            </header>

            {view === 'json' ? (
              <JsonView fields={fields} />
            ) : (
              <>
                <div className="field-grid">
                  {SCALAR_FIELDS.map(([name, label, width]) => {
                    const { confidence, page, absent } = readMeta(meta, name)
                    return (
                      <label key={name} className={`field ${width === 'wide' ? 'field-wide' : ''}`}>
                        <span className="field-label">
                          {label}{' '}
                          {absent ? (
                            <AbsentTag filled={fields[name] != null} />
                          ) : (
                            <ConfidenceBadge confidence={confidence} page={page} />
                          )}
                        </span>
                        <input
                          className={!absent && confidence < CONFIDENCE_THRESHOLD ? 'low' : ''}
                          placeholder="Not on document"
                          value={fields[name] ?? ''}
                          onChange={(e) => updateField(name, e.target.value)}
                        />
                      </label>
                    )
                  })}
                </div>

                <h4>Line items</h4>
                <table className="line-items">
                  <colgroup>
                    <col className="col-description" />
                    <col className="col-qty" />
                    <col className="col-price" />
                    <col className="col-total" />
                    <col className="col-actions" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th>Qty</th>
                      <th>Unit price</th>
                      <th>Line total</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {fields.line_items.map((item, i) => {
                      const itemMeta = meta.line_items?.[i] || {}
                      return (
                        <tr key={i}>
                          {['description', 'quantity', 'unit_price', 'line_total'].map((name) => {
                            // Only low-confidence cells get a badge; the rest show it on hover.
                            const confidence = itemMeta[name]?.confidence
                            const low = confidence !== undefined && confidence < CONFIDENCE_THRESHOLD
                            return (
                              <td key={name}>
                                <input
                                  className={`${name === 'description' ? '' : 'mono'} ${low ? 'low' : ''}`}
                                  type={name === 'description' ? 'text' : 'number'}
                                  step={name === 'quantity' ? 'any' : '0.01'}
                                  value={item[name] ?? ''}
                                  title={
                                    confidence !== undefined ? `${formatPercent(confidence)} confidence` : undefined
                                  }
                                  onChange={(e) => updateLineItem(i, name, e.target.value)}
                                />
                                {low && <ConfidenceBadge confidence={confidence} />}
                              </td>
                            )
                          })}
                          <td>
                            <button
                              className="icon-button"
                              onClick={() => removeLineItem(i)}
                              aria-label="Remove line item"
                            >
                              <Icon name="x" size={14} />
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <button className="link-button" onClick={addLineItem}>
                  <Icon name="plus" size={14} /> Add line item
                </button>

                <div className="totals">
                  {AMOUNT_FIELDS.map(([name, label]) => {
                    const { confidence, page, absent } = readMeta(meta, name)
                    return (
                      <label key={name} className={`total-row ${name === 'total_due' ? 'grand' : ''}`}>
                        <span className="field-label">
                          {label}{' '}
                          {absent ? (
                            <AbsentTag filled={fields[name] != null} />
                          ) : (
                            <ConfidenceBadge confidence={confidence} page={page} />
                          )}
                        </span>
                        <input
                          className={`mono ${!absent && confidence < CONFIDENCE_THRESHOLD ? 'low' : ''}`}
                          placeholder="Not on document"
                          type="number"
                          step="0.01"
                          value={fields[name] ?? ''}
                          onChange={(e) => updateField(name, e.target.value)}
                        />
                      </label>
                    )
                  })}
                  <div className="checks">
                    <span className={subtotalMatches ? 'check-ok' : 'check-bad'}>
                      <Icon name={subtotalMatches ? 'check-circle' : 'alert'} size={13} /> Line items sum to{' '}
                      <span className="mono">{formatMoney(lineSum, fields.currency)}</span>
                    </span>
                    <span className={totalMatches ? 'check-ok' : 'check-bad'}>
                      <Icon name={totalMatches ? 'check-circle' : 'alert'} size={13} /> Subtotal + tax{' '}
                      {totalMatches ? '=' : '≠'} total due
                    </span>
                  </div>
                </div>

                {fields.additional_fields.length > 0 && (
                  <>
                    <h4>Other details on the document</h4>
                    <div className="field-grid">
                      {fields.additional_fields.map((f, i) => (
                        <label key={i} className="field">
                          <span className="field-label">{f.label}</span>
                          <input readOnly value={f.value} />
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </section>
        )}
      </div>
    </main>
  )
}
