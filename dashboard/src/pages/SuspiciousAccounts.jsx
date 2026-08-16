import { useEffect, useState } from 'react'
import { api } from '../api/nexusguardApi'
import LoadingState from '../components/LoadingState'
import ErrorState from '../components/ErrorState'

export default function SuspiciousAccounts() {
  const [accounts, setAccounts] = useState(null)
  const [error, setError] = useState(null)
  const load = () => api.suspiciousAccounts(50).then(setAccounts).catch(e => setError(e.message))
  useEffect(() => { load() }, [])
  if (!accounts && !error) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={load} />
  return <div className="page-stack"><section className="hero-row"><div><div className="section-kicker">ACCOUNT RISK</div><h1>Suspicious accounts</h1><p>Accounts ranked by average risk score using the existing Phase 7 dashboard API.</p></div></section><div className="panel"><div className="table-wrap"><table><thead><tr><th>Account ID</th><th>Transactions</th><th>Avg Risk</th><th>Max Risk</th><th>Blocked</th><th>Review</th></tr></thead><tbody>{accounts.map(a => <tr key={a.account_id}><td><strong>{a.account_id}</strong></td><td>{a.transaction_count}</td><td>{Number(a.average_risk_score).toFixed(2)}</td><td>{Number(a.maximum_risk_score).toFixed(2)}</td><td>{a.blocked_count}</td><td>{a.review_count}</td></tr>)}{!accounts.length && <tr><td colSpan="6"><div className="empty-inline">No suspicious accounts available.</div></td></tr>}</tbody></table></div></div></div>
}
