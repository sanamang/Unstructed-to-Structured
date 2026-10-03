import Icon from './Icon'

const EXPORTS = [
  { file: 'invoices.csv', label: 'Invoices (CSV)' },
  { file: 'line_items.csv', label: 'Line items (CSV)' },
  { file: 'invoices.json', label: 'Invoices (JSON)' },
]

export default function NavSidebar({ status, onStatusChange, counts }) {
  const reviewing = status !== 'unrecognized'
  return (
    <nav className="nav">
      <div className="nav-section">Document queue</div>
      <button className={`nav-item ${reviewing ? 'active' : ''}`} onClick={() => onStatusChange('pending_review')}>
        <Icon name="file-text" size={18} />
        <span>Invoice Review</span>
        {counts.pending_review > 0 && <span className="nav-count">{counts.pending_review}</span>}
      </button>
      <button className={`nav-item ${!reviewing ? 'active' : ''}`} onClick={() => onStatusChange('unrecognized')}>
        <Icon name="file-x" size={18} />
        <span>Unrecognized</span>
        {counts.unrecognized > 0 && <span className="nav-count muted-count">{counts.unrecognized}</span>}
      </button>

      <div className="nav-section">Exports</div>
      {EXPORTS.map(({ file, label }) => (
        <a key={file} className="nav-item" href={`/api/export/${file}`} download>
          <Icon name="download" size={18} />
          <span>{label}</span>
        </a>
      ))}

      <p className="nav-footnote">Exports include accepted invoices only.</p>
    </nav>
  )
}
