import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/nexusguardApi'
import RiskBadge from '../components/RiskBadge'
import DecisionBadge from '../components/DecisionBadge'
import LoadingState from '../components/LoadingState'
import ErrorState from '../components/ErrorState'

function format(value) { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value || 0)) }
function formatAmount(tx) {
  if (tx.source_dataset === 'Mempool.space') {
    return tx.bitcoin_amount == null ? `${format(tx.amount)} USD` : `${format(tx.bitcoin_amount)} BTC`
  }
  if (tx.ingestion_mode === 'DATASET_REPLAY') {
    return tx.amount == null ? '—' : `${format(tx.amount)} ${tx.symbol}`
  }
  return format(tx.transaction_value)
}
function time(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString() }

export default function Transactions() {
  const [transactions, setTransactions] = useState(null)
  const [error, setError] = useState(null)
  const load = () => api.recentTransactions(100).then(setTransactions).catch(e => setError(e.message))
  useEffect(() => { load() }, [])
  if (!transactions && !error) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={load} />
  return <div className="page-stack"><section className="hero-row"><div><div className="section-kicker">TRANSACTION INTELLIGENCE</div><h1>Transactions</h1><p>Inspect actual transactions and open a full risk explanation for any record.</p></div></section><div className="panel"><div className="panel-heading"><div><h2>Recent transactions</h2><span>{transactions.length} records returned by the backend</span></div></div><div className="table-wrap"><table><thead><tr><th>Transaction ID</th><th>Account</th><th>Symbol</th><th>Amount</th><th>Risk</th><th>Score</th><th>Decision</th><th>Timestamp</th></tr></thead><tbody>{transactions.map(tx => <tr key={tx.transaction_id}><td><Link className="table-link" to={`/transactions/${encodeURIComponent(tx.transaction_id)}`}>{tx.transaction_id}</Link></td><td>{tx.account_id}</td><td>{tx.symbol}</td><td>{formatAmount(tx)}</td><td><RiskBadge value={tx.risk_level} /></td><td>{tx.risk_score != null ? Number(tx.risk_score).toFixed(2) : '—'}</td><td><DecisionBadge value={tx.decision} /></td><td>{time(tx.timestamp)}</td></tr>)}{!transactions.length && <tr><td colSpan="8"><div className="empty-inline">No transactions available.</div></td></tr>}</tbody></table></div></div></div>
}
