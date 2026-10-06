import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BrainCircuit, Fingerprint, ShieldAlert, Zap, Clock, Database } from 'lucide-react'
import { api } from '../api/nexusguardApi'
import RiskBadge from '../components/RiskBadge'
import DecisionBadge from '../components/DecisionBadge'
import LoadingState from '../components/LoadingState'
import ErrorState from '../components/ErrorState'

function pct(value) { return value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%` }
function score(value) { return value == null ? '—' : Number(value).toFixed(2) }
function time(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString() }

export default function TransactionDetails() {
  const { transactionId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const load = async () => {
    setError(null)
    try {
      const [transaction, risk] = await Promise.all([
        api.transaction(transactionId), 
        api.transactionRisk(transactionId)
      ])
      setData({ transaction, risk })
    } catch (e) { setError(e.message) }
  }

  useEffect(() => { load() }, [transactionId])
  if (!data && !error) return <LoadingState label="Loading transaction intelligence…" />
  if (error) return <ErrorState message={error} onRetry={load} />

  const { transaction, risk } = data
  const modelRows = [
    ['Random Forest', risk.ml_rf_probability],
    ['XGBoost', risk.ml_xgb_probability],
    ['LSTM', risk.ml_lstm_probability],
    ['Ensemble', risk.ml_probability],
  ]

  const contextItems = [
    ['Transaction ID', transaction.transaction_id],
    ['Source TX ID', transaction.source_transaction_id || 'N/A (Synthetic/Live)'],
    ['Source Dataset', transaction.source_dataset || 'Live / Synthetic Generator'],
    ['Sender', transaction.sender || transaction.account_id],
    ['Receiver', transaction.receiver || 'N/A'],
    ['Symbol', transaction.symbol],
    ['Chain', transaction.chain || 'Crypto'],
    ['Amount', transaction.amount || transaction.transaction_value],
    ['Fee', transaction.fee ? `$${transaction.fee}` : 'N/A'],
    ['Timestamp', time(transaction.timestamp)]
  ]

  return (
    <div className="page-stack">
      <Link to="/transactions" className="back-link"><ArrowLeft size={16} /> Back to transactions</Link>
      
      <section className="hero-row">
        <div>
          <div className="section-kicker">TRANSACTION INVESTIGATION</div>
          <h1>{transaction.transaction_id}</h1>
          <p>{transaction.account_id} · {transaction.symbol} · {time(transaction.timestamp)}</p>
        </div>
        <div className="hero-badges">
          <RiskBadge value={risk.final_risk_level || risk.risk_level} />
          <DecisionBadge value={risk.final_decision || risk.decision} />
        </div>
      </section>

      {/* GROUND TRUTH LABEL BANNER (SEPARATE FROM MODEL DECISION) */}
      {transaction.original_label && (
        <section className="panel" style={{ padding: '16px 20px', borderLeft: '4px solid var(--blue)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.05em' }}>DATASET GROUND TRUTH</span>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, textTransform: 'uppercase', color: transaction.ground_truth_label === 1 ? 'var(--high)' : 'var(--approved)' }}>
                {transaction.original_label} (Label: {transaction.ground_truth_label})
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.05em' }}>NEXUSGUARD DECISION</span>
              <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                <DecisionBadge value={risk.final_decision || risk.decision} />
              </div>
            </div>
          </div>
        </section>
      )}

      <section className="stats-grid four">
        <div className="stat-card">
          <div className="stat-label">Final Risk Score</div>
          <div className="stat-value">{score(risk.final_risk_score)}</div>
          <div className="stat-helper">Combined backend result</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Individual Score</div>
          <div className="stat-value">{score(risk.individual_score)}</div>
          <div className="stat-helper">Rule-based signal</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Behavioral Score</div>
          <div className="stat-value">{score(risk.behavioral_score)}</div>
          <div className="stat-helper">Account history signal</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">ML Risk Score</div>
          <div className="stat-value">{score(risk.ml_risk_score)}</div>
          <div className="stat-helper">Ensemble model signal</div>
        </div>
      </section>

      {/* LATENCY METRICS */}
      <section className="stats-grid three">
        <div className="stat-card">
          <div className="stat-label"><Clock size={14}/> Total Latency</div>
          <div className="stat-value">{transaction.latency_ms ? `${transaction.latency_ms} ms` : '—'}</div>
          <div className="stat-helper">Pipeline end-to-end time</div>
        </div>
        <div className="stat-card">
          <div className="stat-label"><Database size={14}/> Feature Latency</div>
          <div className="stat-value">{transaction.feature_latency_ms ? `${transaction.feature_latency_ms} ms` : '—'}</div>
          <div className="stat-helper">Rule & feature generation</div>
        </div>
        <div className="stat-card">
          <div className="stat-label"><BrainCircuit size={14}/> ML Inference Latency</div>
          <div className="stat-value">{transaction.ml_latency_ms ? `${transaction.ml_latency_ms} ms` : '—'}</div>
          <div className="stat-helper">RF + XGB + LSTM inference</div>
        </div>
      </section>

      <section className="dashboard-grid two-col">
        <div className="panel">
          <div className="panel-heading">
            <div><h2>Transaction context</h2><span>Source record from MongoDB</span></div>
            <Fingerprint size={20} />
          </div>
          <div className="detail-grid">
            {contextItems.map(([k,v]) => (
              <div className="detail-item" key={k}>
                <span>{k}</span>
                <strong>{v == null ? '—' : String(v)}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-heading">
            <div><h2>Decision classification</h2><span>Final risk classification returned by backend</span></div>
            <ShieldAlert size={20} />
          </div>
          <div className="decision-center">
            <RiskBadge value={risk.final_risk_level || risk.risk_level} />
            <div className="decision-score">{score(risk.final_risk_score)}</div>
            <DecisionBadge value={risk.final_decision || risk.decision} />
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><h2>Model intelligence</h2><span>Actual RF, XGBoost and LSTM probabilities</span></div>
          <BrainCircuit size={20} />
        </div>
        <div className="model-list">
          {modelRows.map(([name, val]) => (
            <div className="model-row" key={name}>
              <div className="model-name">{name}</div>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, Number(val || 0) * 100))}%` }} />
              </div>
              <strong>{pct(val)}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="dashboard-grid two-col">
        <div className="panel">
          <div className="panel-heading">
            <div><h2>Why this transaction was flagged</h2><span>Rule-based reasons and behavioral evidence</span></div>
            <Zap size={20} />
          </div>
          <div className="reason-list">
            {(risk.reasons || []).map((reason, i) => (
              <div className="reason-item" key={`${reason}-${i}`}>
                <span className="reason-index">{i + 1}</span>
                <span>{reason}</span>
              </div>
            ))}
            {!(risk.reasons || []).length && <div className="empty-inline">No risk reasons were returned by the backend.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-heading">
            <div><h2>Behavioral signals</h2><span>Signals generated from account history</span></div>
          </div>
          <div className="signal-list">
            {(risk.behavioral_signals || []).map((signal, i) => (
              <div className="signal-card" key={`${signal.type}-${i}`}>
                <div className="signal-top">
                  <strong>{signal.type || 'signal'}</strong>
                  <span className={`signal-severity ${String(signal.severity || 'low').toLowerCase()}`}>{signal.severity || 'low'}</span>
                </div>
                <div>{signal.message || 'No message supplied.'}</div>
              </div>
            ))}
            {!(risk.behavioral_signals || []).length && <div className="empty-inline">No behavioral signals returned.</div>}
          </div>
        </div>
      </section>
    </div>
  )
}
