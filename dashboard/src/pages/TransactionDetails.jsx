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
function time(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
    hour12: false,
  }).format(date) + ' IST'
}

export default function TransactionDetails() {
  const { transactionId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [historicalEvaluation, setHistoricalEvaluation] = useState(null)

  const load = async () => {
    setError(null)
    try {
      const [transaction, risk] = await Promise.all([
        api.transaction(transactionId), 
        api.transactionRisk(transactionId)
      ])
      setData({ transaction, risk })
      try {
        const status = await api.datasetReplayStatus()
        if (status.dataset_id && status.dataset_id !== 'none') {
          const analysis = await api.datasetAnalysis(status.dataset_id)
          setHistoricalEvaluation({ status, analysis })
        } else {
          setHistoricalEvaluation(null)
        }
      } catch (evaluationError) {
        console.error('Historical CSV evaluation is unavailable', evaluationError)
        setHistoricalEvaluation(null)
      }
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
  const finalScore = risk.final_risk_score ?? risk.risk_score
  const finalDecision = risk.final_decision || risk.decision || 'UNKNOWN'
  const ensembleAvailable = risk.model_availability?.Ensemble?.available
  const scoreMethod = ensembleAvailable
    ? 'The final score combines 40% rule/behavior score and 60% available-model score.'
    : 'Required ML artifacts are unavailable, so the final score uses rule/behavior signals only; no missing-model score is substituted.'
  const decisionPolicy = finalDecision === 'BLOCK'
    ? `Blocked: the final risk score is ${score(finalScore)}; blocking starts at 80, and a critical fraud rule can also force a block.`
    : finalDecision === 'REVIEW'
      ? `Sent for review: the final risk score is ${score(finalScore)}; the review band is 50 to below 80.`
      : finalDecision === 'APPROVE'
        ? `Approved: the final risk score is ${score(finalScore)}; approval requires a score below 50 with no critical override.`
        : 'The backend did not return a final decision policy result.'
  const isMempoolTransaction = transaction.source_dataset === 'Mempool.space'
  const isDatasetReplay = transaction.ingestion_mode === 'DATASET_REPLAY'

  const contextItems = [
    ['Transaction ID', transaction.transaction_id],
    ['Source TX ID', transaction.source_transaction_id],
    ['Data source', transaction.source_dataset],
    ['Observed at', transaction.mempool_observed_at],
    ['Sender', transaction.sender],
    ['Receiver', transaction.receiver],
    ['Symbol', transaction.symbol],
    ['Network', transaction.network || transaction.chain],
    ['Bitcoin amount', transaction.bitcoin_amount == null ? undefined : `${Number(transaction.bitcoin_amount).toFixed(8)} BTC`],
    [
      isDatasetReplay ? 'Source amount' : isMempoolTransaction ? 'USD value at observed spot' : 'Amount',
      transaction.amount == null
        ? undefined
        : isDatasetReplay
          ? `${Number(transaction.amount).toLocaleString('en-US', { maximumFractionDigits: 8 })} ${transaction.symbol}`
          : `$${Number(transaction.amount).toFixed(2)}`,
    ],
    ['Fee', transaction.fee_sats == null ? undefined : `${transaction.fee_sats} sats`],
    ['Timestamp', time(transaction.timestamp)]
  ].filter(([, value]) => value !== null && value !== undefined && value !== '')
  const rawDecision = String(finalDecision).toUpperCase()
  const decisionHeading = rawDecision === 'BLOCK'
    ? 'Why this transaction was blocked'
    : rawDecision === 'REVIEW'
      ? 'Why this transaction requires review'
      : rawDecision === 'APPROVE'
        ? 'Why this transaction was allowed'
        : 'Decision explanation'
  const modelComparison = historicalEvaluation?.status?.model_comparison || []
  const historicalMetrics = historicalEvaluation?.status?.performance_metrics || {}

  return (
    <div className="page-stack">
      <Link to="/transactions" className="back-link"><ArrowLeft size={16} /> Back to transactions</Link>
      
      <section className="hero-row">
        <div>
          <div className="section-kicker">{isMempoolTransaction ? 'LIVE BITCOIN TRANSACTION ANALYSIS' : 'TRANSACTION INVESTIGATION'}</div>
          <h1>{transaction.transaction_id}</h1>
          <p>{transaction.account_id} · {transaction.symbol} · {time(transaction.timestamp)}</p>
        </div>
        <div className="hero-badges">
          <RiskBadge value={risk.final_risk_level || risk.risk_level} />
          <DecisionBadge value={risk.final_decision || risk.decision} />
        </div>
      </section>

      {/* Dataset labels are displayed only for historical CSV transactions. */}
      {transaction.ground_truth_label !== undefined && transaction.ground_truth_label !== null && (
        <section className="panel" style={{ padding: '16px 20px', borderLeft: '4px solid var(--blue)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.05em' }}>DATASET GROUND TRUTH</span>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, textTransform: 'uppercase', color: transaction.ground_truth_label === 1 ? 'var(--high)' : 'var(--approved)' }}>
                {transaction.original_label || 'Dataset label'} (Label: {transaction.ground_truth_label})
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
        {!isMempoolTransaction && <div className="stat-card">
          <div className="stat-label">ML Risk Score</div>
          <div className="stat-value">{score(risk.ml_risk_score)}</div>
          <div className="stat-helper">Ensemble model signal</div>
        </div>}
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

      {isMempoolTransaction && (
        <section className="dashboard-grid two-col">
          {[
            ['Inputs', transaction.vin || [], (input) => input.prevout?.scriptpubkey_address],
            ['Outputs', transaction.vout || [], (output) => output.scriptpubkey_address],
          ].map(([title, items, addressOf]) => (
            <div className="panel" key={title}>
              <div className="panel-heading">
                <div><h2>Bitcoin {title}</h2><span>Transaction data returned by Mempool.space</span></div>
              </div>
              {items.length ? (
                <div className="reason-list">
                  {items.map((item, index) => (
                    <div className="reason-item" key={`${title}-${index}`}>
                      <span className="reason-index">{index + 1}</span>
                      <span>
                        {addressOf(item) || 'Address not present in source data'}
                        {item.value != null && ` · ${Number(item.value).toLocaleString()} sats`}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-inline">No {title.toLowerCase()} were returned by the source.</div>
              )}
            </div>
          ))}
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div><h2>Model intelligence</h2><span>Per-model probabilities are shown only when the model artifacts are available</span></div>
          <BrainCircuit size={20} />
        </div>
        <div className="model-list">
          {modelRows.map(([name, val]) => (
            <div className="model-row" key={name}>
              <div className="model-name">{name}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${Math.min(100, Math.max(0, Number(val || 0) * 100))}%`,
                    opacity: risk.model_availability?.[name]?.available ? 1 : 0.25,
                  }}
                />
              </div>
              <strong>{risk.model_availability?.[name]?.available ? pct(val) : 'Unavailable'}</strong>
              {!risk.model_availability?.[name]?.available && (
                <span className="muted">
                  Missing: {(risk.model_availability?.[name]?.missing_artifacts || []).join(', ') || 'required model files'}
                </span>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="dashboard-grid two-col">
        <div className="panel">
          <div className="panel-heading">
            <div><h2>{decisionHeading}</h2><span>NexusGuard’s recorded evidence for this risk decision</span></div>
            <Zap size={20} />
          </div>
          <div className="empty-inline" style={{ marginBottom: '12px' }}>
            {decisionPolicy} {scoreMethod} A critical rule can override the normal threshold.
          </div>
          <div className="reason-list">
            {(risk.reasons || []).map((reason, i) => (
              <div className="reason-item" key={`${reason}-${i}`}>
                <span className="reason-index">{i + 1}</span>
                <span>{reason}</span>
              </div>
            ))}
            {!(risk.reasons || []).length && (
              <div className="empty-inline">The backend returned no additional rule or behavioral reason strings for this decision.</div>
            )}
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

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Historical CSV Model Evaluation</h2>
            <span>Offline labeled-dataset results; live Mempool transactions have no assumed ground-truth label.</span>
          </div>
        </div>
        {historicalEvaluation ? (
          <>
            <div className="stats-grid four">
              {[
                ['Dataset', historicalEvaluation.analysis.csv_filename],
                ['Total records', historicalEvaluation.analysis.total_records],
                ['Accuracy', pct(historicalMetrics.accuracy)],
                ['Precision', pct(historicalMetrics.precision)],
                ['Recall', pct(historicalMetrics.recall)],
                ['F1 score', pct(historicalMetrics.f1_score)],
              ].map(([label, value]) => (
                <div className="stat-card" key={label}>
                  <div className="stat-label">{label}</div>
                  <div className="stat-value">{value ?? '—'}</div>
                </div>
              ))}
            </div>
            <div className="table-wrap compact" style={{ marginTop: '16px' }}>
              <table>
                <thead>
                  <tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1 Score</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {modelComparison.map((row) => (
                    <tr key={row.model}>
                      <td>{row.model}</td>
                      <td>{pct(row.accuracy)}</td>
                      <td>{pct(row.precision)}</td>
                      <td>{pct(row.recall)}</td>
                      <td>{pct(row.f1_score)}</td>
                      <td>{row.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="empty-inline">
            No completed labeled CSV replay is available yet. Run Batch evaluation to populate these historical metrics.
          </div>
        )}
      </section>
    </div>
  )
}
