import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, ShieldCheck, ShieldX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/nexusguardApi'
import StatCard from '../components/StatCard'
import RiskBadge from '../components/RiskBadge'
import DecisionBadge from '../components/DecisionBadge'
import LoadingState from '../components/LoadingState'
import ErrorState from '../components/ErrorState'
import RiskDistributionChart from '../charts/RiskDistributionChart'
import DecisionChart from '../charts/DecisionChart'
import ActivityChart from '../charts/ActivityChart'

function formatNumber(value) { return new Intl.NumberFormat().format(Number(value || 0)) }
function formatMoney(value) { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value || 0)) }
function formatTime(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString() }

export default function Dashboard({ refreshKey }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const load = async () => {
    setError(null)
    try {
      const [summary, distribution, transactions, accounts] = await Promise.all([
        api.summary(), api.riskDistribution(), api.recentTransactions(100), api.suspiciousAccounts(5),
      ])
      setData({ summary, distribution, transactions, accounts })
    } catch (err) { setError(err.message) }
  }

  useEffect(() => { load() }, [refreshKey])

  const fraudRate = useMemo(() => {
    const total = Number(data?.summary?.total_transactions || 0)
    if (!total) return 0
    return (((Number(data.summary.review || 0) + Number(data.summary.blocked || 0)) / total) * 100).toFixed(1)
  }, [data])

  if (!data && !error) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={load} />

  const { summary, distribution, transactions, accounts } = data
  return (
    <div className="page-stack">
      <section className="hero-row">
        <div>
          <div className="section-kicker">LIVE MONITORING</div>
          <h1>Security overview</h1>
          <p>Track transaction risk, model signals, and suspicious account activity from the live NexusGuard backend.</p>
        </div>
        <div className="hero-chip"><ShieldCheck size={17} /> Backend connected</div>
      </section>

      <section className="stats-grid">
        <StatCard label="Total Transactions" value={formatNumber(summary.total_transactions)} helper={`${formatNumber(summary.processed_transactions)} processed`} />
        <StatCard label="Approved" value={formatNumber(summary.approved)} helper="Low-risk decisions" tone="approved" />
        <StatCard label="Review" value={formatNumber(summary.review)} helper="Requires investigation" tone="medium" />
        <StatCard label="Blocked" value={formatNumber(summary.blocked)} helper="High-risk decisions" tone="high" />
        <StatCard label="Fraud Rate" value={`${fraudRate}%`} helper="Review + blocked / total" tone="medium" />
        <StatCard label="High Risk" value={formatNumber(summary.risk_levels?.HIGH)} helper={`Avg score ${Number(summary.average_risk_score || 0).toFixed(1)}`} tone="high" />
      </section>

      <section className="dashboard-grid two-col">
        <div className="panel">
          <div className="panel-heading"><div><h2>Risk distribution</h2><span>All transactions in MongoDB</span></div></div>
          <div className="chart-panel-body"><RiskDistributionChart distribution={distribution} /><div className="legend-list">{[['LOW','var(--low)'],['MEDIUM','var(--medium)'],['HIGH','var(--high)']].map(([name, color]) => <div className="legend-item" key={name}><span className="legend-dot" style={{ background: color }} />{name}<strong>{formatNumber(distribution?.[name])}</strong></div>)}</div></div>
        </div>
        <div className="panel">
          <div className="panel-heading"><div><h2>Decision mix</h2><span>Backend decision outcomes</span></div></div>
          <div className="chart-panel-body"><DecisionChart summary={summary} /><div className="legend-list"><div className="legend-item"><span className="legend-dot" style={{ background: 'var(--approved)' }} />Approved<strong>{formatNumber(summary.approved)}</strong></div><div className="legend-item"><span className="legend-dot" style={{ background: 'var(--medium)' }} />Review<strong>{formatNumber(summary.review)}</strong></div><div className="legend-item"><span className="legend-dot" style={{ background: 'var(--high)' }} />Blocked<strong>{formatNumber(summary.blocked)}</strong></div></div></div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>Transaction activity</h2><span>Actual timestamps from recent backend records</span></div><Link to="/analytics" className="text-link">Open analytics <ArrowUpRight size={16} /></Link></div>
        <div className="large-chart"><ActivityChart transactions={transactions} /></div>
      </section>

      <section className="dashboard-grid two-col">
        <div className="panel">
          <div className="panel-heading"><div><h2>Recent transactions</h2><span>Latest 100 records available to the UI</span></div><Link to="/transactions" className="text-link">View all <ArrowUpRight size={16} /></Link></div>
          <div className="table-wrap compact"><table><thead><tr><th>Transaction</th><th>Risk</th><th>Decision</th><th>Value</th></tr></thead><tbody>
            {transactions.slice(0, 8).map(tx => <tr key={tx.transaction_id}><td><Link className="table-link" to={`/transactions/${encodeURIComponent(tx.transaction_id)}`}>{tx.transaction_id}</Link><div className="muted">{tx.account_id} · {tx.symbol}</div></td><td><RiskBadge value={tx.risk_level} /></td><td><DecisionBadge value={tx.decision} /></td><td>{formatMoney(tx.transaction_value)}</td></tr>)}
            {!transactions.length && <tr><td colSpan="4"><div className="empty-inline">No transactions available.</div></td></tr>}
          </tbody></table></div>
        </div>
        <div className="panel">
          <div className="panel-heading"><div><h2>Top suspicious accounts</h2><span>Ranked by average risk score</span></div><Link to="/accounts" className="text-link">Investigate <ArrowUpRight size={16} /></Link></div>
          <div className="account-list">{accounts.map(account => <Link to={`/accounts?account=${encodeURIComponent(account.account_id)}`} className="account-row" key={account.account_id}><div><strong>{account.account_id}</strong><span>{account.transaction_count} txns · {account.blocked_count} blocked · {account.review_count} review</span></div><div className="account-score"><span>{Number(account.maximum_risk_score || 0).toFixed(1)}</span><ShieldX size={15} /></div></Link>)}{!accounts.length && <div className="empty-inline">No suspicious-account records available.</div>}</div>
        </div>
      </section>
    </div>
  )
}
