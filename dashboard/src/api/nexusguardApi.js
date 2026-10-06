const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  })

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const message = payload?.detail || `Request failed (${response.status})`
    throw new Error(message)
  }

  return payload
}

export const api = {
  summary: () => request('/dashboard/summary'),
  recentTransactions: (limit = 100) => request(`/dashboard/recent-transactions?limit=${limit}`),
  riskDistribution: () => request('/dashboard/risk-distribution'),
  suspiciousAccounts: (limit = 10) => request(`/dashboard/suspicious-accounts?limit=${limit}`),
  transaction: (id) => request(`/transactions/${encodeURIComponent(id)}`),
  transactionRisk: (id) => request(`/transactions/${encodeURIComponent(id)}/risk`),
  transactionBehavior: (id) => request(`/transactions/${encodeURIComponent(id)}/behavior`),
  transactionMl: (id) => request(`/transactions/${encodeURIComponent(id)}/ml`),
  health: () => request('/health'),
  
  // Dataset Replay API methods
  listDatasets: () => request('/demo/dataset-replay/datasets'),
  startDatasetReplay: (payload) => request('/demo/dataset-replay/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  stopDatasetReplay: () => request('/demo/dataset-replay/stop', { method: 'POST' }),
  resetDatasetReplay: () => request('/demo/dataset-replay/reset', { method: 'POST' }),
  datasetReplayStatus: () => request('/demo/dataset-replay/status'),
}

export { API_BASE_URL }

