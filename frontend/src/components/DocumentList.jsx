const STATUS_TABS = [
  { value: 'pending_review', label: 'Needs Review' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'unrecognized', label: 'Unrecognized' },
  { value: '', label: 'All' },
]

function StatusPill({ status }) {
  return <span className={`status-pill status-${status}`}>{status.replace('_', ' ')}</span>
}

export default function DocumentList({
  documents,
  loading,
  status,
  onStatusChange,
  selectedId,
  onSelect,
  onUpload,
  uploading,
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>Invoice Review</h1>
        <label className="upload-button">
          {uploading ? 'Uploading…' : 'Upload invoice'}
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp"
            disabled={uploading}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) onUpload(file)
              e.target.value = ''
            }}
          />
        </label>
      </div>

      <div className="status-tabs">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            className={status === tab.value ? 'active' : ''}
            onClick={() => onStatusChange(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading && <p className="muted">Loading…</p>}
      {!loading && documents.length === 0 && <p className="muted">No documents here.</p>}

      <ul className="document-list">
        {documents.map((doc) => (
          <li key={doc.id}>
            <button className={doc.id === selectedId ? 'selected' : ''} onClick={() => onSelect(doc.id)}>
              <div className="row">
                <strong>{doc.vendor_name || doc.source_filename}</strong>
                <StatusPill status={doc.status} />
              </div>
              <div className="row muted">
                <span>{doc.total_due != null ? `$${doc.total_due.toFixed(2)}` : '—'}</span>
                {doc.issue_count > 0 && <span className="issue-count">{doc.issue_count} issue(s)</span>}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
