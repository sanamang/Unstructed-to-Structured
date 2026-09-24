import { useCallback, useEffect, useState } from 'react'
import './App.css'
import DocumentDetail from './components/DocumentDetail'
import DocumentList from './components/DocumentList'
import { getDocument, listDocuments, reviewDocument, uploadDocument } from './api'

export default function App() {
  const [status, setStatus] = useState('pending_review')
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const refreshList = useCallback(async (currentStatus) => {
    setLoading(true)
    try {
      const docs = await listDocuments(currentStatus)
      setDocuments(docs)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshList(status)
  }, [status, refreshList])

  useEffect(() => {
    if (!selectedId) {
      setSelectedDoc(null)
      return
    }
    getDocument(selectedId).then(setSelectedDoc).catch((e) => setError(String(e)))
  }, [selectedId])

  const handleUpload = async (file) => {
    setUploading(true)
    setError(null)
    try {
      const doc = await uploadDocument(file)
      await refreshList(status)
      setSelectedId(doc.id)
    } catch (e) {
      setError(String(e))
    } finally {
      setUploading(false)
    }
  }

  const handleSave = async (docId, fields) => {
    setSaving(true)
    setError(null)
    try {
      const updated = await reviewDocument(docId, fields)
      setSelectedDoc(updated)
      await refreshList(status)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="app">
      {error && (
        <div className="error-banner" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      <DocumentList
        documents={documents}
        loading={loading}
        status={status}
        onStatusChange={setStatus}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onUpload={handleUpload}
        uploading={uploading}
      />
      <DocumentDetail document={selectedDoc} onSave={handleSave} saving={saving} />
    </div>
  )
}
