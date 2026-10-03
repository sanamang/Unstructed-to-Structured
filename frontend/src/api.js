const BASE = '/api'

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export function checkHealth() {
  return request('/health')
}

export function listDocuments(status) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return request(`/documents${qs}`)
}

export function getDocument(id) {
  return request(`/documents/${id}`)
}

export function reviewDocument(id, fields) {
  return request(`/documents/${id}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fields }),
  })
}

export function structureDocument(id) {
  return request(`/documents/${id}/structure`, { method: 'POST' })
}

export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: formData })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}
