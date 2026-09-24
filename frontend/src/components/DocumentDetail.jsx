import { useEffect, useState } from 'react'
import ConfidenceBadge from './ConfidenceBadge'

const SCALAR_FIELDS = [
  ['vendor_name', 'Vendor'],
  ['invoice_number', 'Invoice #'],
  ['invoice_date', 'Invoice date'],
  ['due_date', 'Due date'],
  ['currency', 'Currency'],
  ['subtotal', 'Subtotal'],
  ['tax', 'Tax'],
  ['total_due', 'Total due'],
]

const NUMERIC_FIELDS = new Set(['subtotal', 'tax', 'total_due', 'quantity', 'unit_price', 'line_total'])

function emptyLineItem() {
  return { description: '', quantity: 0, unit_price: 0, line_total: 0 }
}

export default function DocumentDetail({ document, onSave, saving }) {
  const [fields, setFields] = useState(null)
  const [pageIndex, setPageIndex] = useState(0)

  useEffect(() => {
    if (!document) return
    setPageIndex(0)
    if (document.doc_type !== 'invoice') {
      setFields(null)
      return
    }
    setFields({
      vendor_name: document.vendor_name,
      invoice_number: document.invoice_number,
      invoice_date: document.invoice_date,
      due_date: document.due_date,
      currency: document.currency,
      subtotal: document.subtotal,
      tax: document.tax,
      total_due: document.total_due,
      line_items: document.line_items.map((li) => ({ ...li })),
    })
  }, [document])

  if (!document) {
    return (
      <main className="detail empty">
        <p className="muted">Select a document from the list.</p>
      </main>
    )
  }

  const updateField = (name, rawValue) => {
    const value = NUMERIC_FIELDS.has(name) ? (rawValue === '' ? null : Number(rawValue)) : rawValue || null
    setFields((f) => ({ ...f, [name]: value }))
  }

  const updateLineItem = (index, name, rawValue) => {
    const value = NUMERIC_FIELDS.has(name) ? Number(rawValue) : rawValue
    setFields((f) => {
      const line_items = f.line_items.map((li, i) => (i === index ? { ...li, [name]: value } : li))
      return { ...f, line_items }
    })
  }

  const addLineItem = () => setFields((f) => ({ ...f, line_items: [...f.line_items, emptyLineItem()] }))
  const removeLineItem = (index) =>
    setFields((f) => ({ ...f, line_items: f.line_items.filter((_, i) => i !== index) }))

  const meta = document.field_meta || {}
  const pageUrl = document.page_urls[pageIndex]

  return (
    <main className="detail">
      <div className="detail-columns">
        <section className="page-viewer">
          {pageUrl ? (
            <img src={pageUrl} alt={`Page ${pageIndex + 1}`} />
          ) : (
            <p className="muted">No page image available.</p>
          )}
          {document.page_urls.length > 1 && (
            <div className="page-nav">
              {document.page_urls.map((_, i) => (
                <button key={i} className={i === pageIndex ? 'active' : ''} onClick={() => setPageIndex(i)}>
                  {i + 1}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="fields-panel">
          <header>
            <h2>{document.source_filename}</h2>
            <span className={`status-pill status-${document.status}`}>{document.status.replace('_', ' ')}</span>
          </header>

          <p className="muted">
            Classified as <strong>{document.doc_type}</strong> (
            <ConfidenceBadge confidence={document.classification_confidence} />)
          </p>

          {document.validation_issues.length > 0 && (
            <div className="issues">
              <strong>Validation issues:</strong>
              <ul>
                {document.validation_issues.map((issue, i) => (
                  <li key={i}>
                    <code>{issue.rule}</code>
                    {issue.field && <> — {issue.field}</>}: {issue.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!fields && <p className="muted">No extracted invoice fields for this document.</p>}

          {fields && (
            <>
              <div className="field-grid">
                {SCALAR_FIELDS.map(([name, label]) => (
                  <label key={name} className="field">
                    <span className="field-label">
                      {label} <ConfidenceBadge confidence={meta[name]?.confidence} page={meta[name]?.page} />
                    </span>
                    <input
                      value={fields[name] ?? ''}
                      type={NUMERIC_FIELDS.has(name) ? 'number' : 'text'}
                      step="0.01"
                      onChange={(e) => updateField(name, e.target.value)}
                    />
                  </label>
                ))}
              </div>

              <h3>Line items</h3>
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
                        <td>
                          <input
                            value={item.description}
                            onChange={(e) => updateLineItem(i, 'description', e.target.value)}
                          />
                          <ConfidenceBadge confidence={itemMeta.description?.confidence} />
                        </td>
                        <td>
                          <input
                            type="number"
                            value={item.quantity}
                            onChange={(e) => updateLineItem(i, 'quantity', e.target.value)}
                          />
                          <ConfidenceBadge confidence={itemMeta.quantity?.confidence} />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={item.unit_price}
                            onChange={(e) => updateLineItem(i, 'unit_price', e.target.value)}
                          />
                          <ConfidenceBadge confidence={itemMeta.unit_price?.confidence} />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={item.line_total}
                            onChange={(e) => updateLineItem(i, 'line_total', e.target.value)}
                          />
                          <ConfidenceBadge confidence={itemMeta.line_total?.confidence} />
                        </td>
                        <td>
                          <button className="link-button" onClick={() => removeLineItem(i)}>
                            remove
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <button className="link-button" onClick={addLineItem}>
                + add line item
              </button>

              <div className="actions">
                <button
                  className="primary"
                  disabled={saving}
                  onClick={() => onSave(document.id, fields)}
                >
                  {saving ? 'Saving…' : 'Confirm & resolve'}
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  )
}
