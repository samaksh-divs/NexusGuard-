import { useEffect, useState } from 'react'
import { api } from '../api/nexusguardApi'
import LoadingState from '../components/LoadingState'
import ErrorState from '../components/ErrorState'
import RiskDistributionChart from '../charts/RiskDistributionChart'
import DecisionChart from '../charts/DecisionChart'
import ActivityChart from '../charts/ActivityChart'

export default function RiskAnalytics() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const load = async () => { setError(null); try { const [summary, distribution, transactions] = await Promise.all([api.summary(), api.riskDistribution(), api.recentTransactions(100)]); setData({ summary, distribution, transactions }) } catch (e) { setError(e.message) } }
  useEffect(() => { load() }, [])
  if (!data && !error) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={load} />
  return <div className="page-stack"><section className="hero-row"><div><div className="section-kicker">RISK ANALYTICS</div><h1>Risk analytics</h1><p>Visualize actual backend risk, decision, and recent transaction activity.</p></div></section><section className="dashboard-grid two-col"><div className="panel"><div className="panel-heading"><div><h2>Risk distribution</h2><span>LOW / MEDIUM / HIGH</span></div></div><div className="chart-panel-body"><RiskDistributionChart distribution={data.distribution} /></div></div><div className="panel"><div className="panel-heading"><div><h2>Decision distribution</h2><span>APPROVE / REVIEW / BLOCK</span></div></div><div className="chart-panel-body"><DecisionChart summary={data.summary} /></div></div></section><div className="panel"><div className="panel-heading"><div><h2>Recent activity</h2><span>Derived only from real timestamps returned by the API</span></div></div><div className="large-chart"><ActivityChart transactions={data.transactions} /></div></div></div>
}
