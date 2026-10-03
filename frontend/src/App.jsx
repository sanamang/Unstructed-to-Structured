import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { checkHealth, getDocument, listDocuments, reviewDocument, structureDocument, uploadDocument } from './api'
import DocumentDetail from './components/DocumentDetail'
import DocumentList from './components/DocumentList'
import ErrorBoundary from './components/ErrorBoundary'
import Icon from './components/Icon'
import NavSidebar from './components/NavSidebar'

const EXPORTS = [
  ['CSV', 'invoices.csv'],
  ['Line items CSV', 'line_items.csv'],
  ['JSON', 'invoices.json'],
]

const ACCEPTED_TYPES = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp'

function matchesQuery(doc, query) {
  if (!query) return true
  const haystack = [doc.vendor_name, doc.invoice_number, doc.source_filename, doc.total_due?.toFixed(2), doc.currency]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return query
    .toLowerCase()
    .replace(/[$,]/g, '')
    .split(/\s+/)
    .every((term) => haystack.includes(term))
}

export default function App() {
  // The whole list is fetched once and filtered client-side, so tab counts
  // and KPIs always agree with what's shown.
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('pending_review')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [saving, setSaving] = useState(false)
  const [structuringId, setStructuringId] = useState(null)
  const [notice, setNotice] = useState(null)
  const [uploading, setUploading] = useState(null) // filename being processed
  const [dragging, setDragging] = useState(false)
  const [apiOnline, setApiOnline] = useState(null)
  const [error, setError] = useState(null)
  const fileInput = useRef(null)
  const dragDepth = useRef(0)

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    checkHealth()
      .then(() => setApiOnline(true))
      .catch(() => setApiOnline(false))
  }, [refresh])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    getDocument(selectedId)
      .then((doc) => !cancelled && setSelectedDoc(doc))
      .catch((e) => !cancelled && setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const activeDoc = selectedDoc && selectedDoc.id === selectedId ? selectedDoc : null

  const counts = useMemo(() => {
    const c = { uploaded: 0, pending_review: 0, accepted: 0, unrecognized: 0 }
    for (const doc of documents) c[doc.status] = (c[doc.status] || 0) + 1
    return c
  }, [documents])

  const tabs = [
    { value: 'uploaded', label: 'New', count: counts.uploaded },
    { value: 'pending_review', label: 'Needs Review', count: counts.pending_review },
    { value: 'accepted', label: 'Accepted', count: counts.accepted },
    { value: 'unrecognized', label: 'Unrecognized', count: counts.unrecognized },
    { value: '', label: 'All' },
  ]

  const visible = documents.filter((d) => (!status || d.status === status) && matchesQuery(d, query))

  const handleFiles = async (fileList) => {
    const files = [...(fileList || [])]
    if (files.length === 0) return
    setError(null)
    let last = null
    for (const file of files) {
      setUploading(file.name)
      try {
        last = await uploadDocument(file)
      } catch (e) {
        setError(`${file.name}: ${e}`)
      }
    }
    setUploading(null)
    await refresh()
    if (last) {
      setStatus(last.status)
      setQuery('')
      setSelectedDoc(last)
      setSelectedId(last.id)
    }
  }

  const STRUCTURED_NOTICES = {
    accepted: 'Structured and auto-accepted: every field passed validation.',
    pending_review: 'Structured. Some fields need a quick review before accepting.',
    unrecognized: 'This document doesn’t look like an invoice, so no fields were extracted.',
  }

  const handleStructure = async (docId) => {
    setStructuringId(docId)
    setError(null)
    try {
      const structured = await structureDocument(docId)
      await refresh()
      setStatus(structured.status)
      setSelectedDoc(structured)
      setNotice(STRUCTURED_NOTICES[structured.status])
      setTimeout(() => setNotice(null), 5000)
    } catch (e) {
      setError(String(e))
    } finally {
      setStructuringId(null)
    }
  }

  const handleSave = async (docId, fields) => {
    setSaving(true)
    setError(null)
    try {
      setSelectedDoc(await reviewDocument(docId, fields))
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')
  const dragHandlers = {
    onDragEnter: (e) => {
      if (!hasFiles(e)) return
      dragDepth.current += 1
      setDragging(true)
    },
    onDragLeave: (e) => {
      if (!hasFiles(e)) return
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    },
    onDragOver: (e) => hasFiles(e) && e.preventDefault(),
    onDrop: (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      if (!uploading) handleFiles(e.dataTransfer.files)
    },
  }

  return (
    <div className="app" {...dragHandlers}>
      {error && (
        <div className="error-banner" onClick={() => setError(null)} title="Click to dismiss">
          <Icon name="alert" size={16} /> {error}
        </div>
      )}
      {notice && (
        <div className="notice-banner" onClick={() => setNotice(null)}>
          <Icon name="check-circle" size={16} /> {notice}
        </div>
      )}
      {dragging && (
        <div className="drop-overlay">
          <div>
            <Icon name="upload" size={40} />
            <p>Drop invoices to upload</p>
            <span>PDF, PNG, JPG, TIFF or BMP</span>
          </div>
        </div>
      )}

      <NavSidebar status={status} onStatusChange={setStatus} counts={counts} />

      <div className="main">
        <header className="page-header">
          <div className="title-row">
            <h1>Invoice Review</h1>
            <span className={`engine-pill ${apiOnline === false ? 'offline' : ''}`}>
              <span className="pulse" />
              {apiOnline === false ? 'API offline' : 'Claude vision extraction'}
            </span>
            <span className="subtitle">• Classify → extract → validate → review</span>
          </div>

          <div className="toolbar">
            <div className="export-group">
              <span>Export accepted:</span>
              {EXPORTS.map(([label, file]) => (
                <a key={file} className="chip-button" href={`/api/export/${file}`} download>
                  {label}
                </a>
              ))}
            </div>
            <button className="upload-button" disabled={!!uploading} onClick={() => fileInput.current?.click()}>
              <Icon name="upload" size={18} />
              {uploading ? `Processing ${uploading}…` : 'Upload invoice'}
              {!uploading && <span className="hint">(or drag & drop)</span>}
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              accept={ACCEPTED_TYPES}
              onChange={(e) => {
                handleFiles(e.target.files)
                e.target.value = ''
              }}
            />
          </div>
        </header>

        <div className="workspace">
          <DocumentList
            tabs={tabs}
            status={status}
            onStatusChange={setStatus}
            query={query}
            onQueryChange={setQuery}
            documents={visible}
            loading={loading}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <ErrorBoundary resetKey={activeDoc?.id}>
            <DocumentDetail
              key={activeDoc ? `${activeDoc.id}:${activeDoc.status}:${activeDoc.resolved_at}` : 'none'}
              document={activeDoc}
              onSave={handleSave}
              saving={saving}
              onStructure={() => handleStructure(activeDoc.id)}
              structuring={structuringId === activeDoc?.id}
            />
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
