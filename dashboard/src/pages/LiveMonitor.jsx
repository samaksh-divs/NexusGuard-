import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Play, Square, RotateCcw, Activity, Database, Server, Zap, CheckCircle2, AlertTriangle, ShieldX } from 'lucide-react'
import DecisionBadge from '../components/DecisionBadge'
import RiskBadge from '../components/RiskBadge'
import { api } from '../api/nexusguardApi'

function formatMoney(value) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value || 0)) }
function formatTime(value) { return value ? new Date(value).toLocaleTimeString() : '—' }

export default function LiveMonitor() {
  const [transactions, setTransactions] = useState([])
  const [connected, setConnected] = useState(false)
  
  // Ingestion Mode State: 'DEMO' | 'DATASET_REPLAY' | 'LIVE_API'
  const [mode, setMode] = useState('DATASET_REPLAY')
  
  // Dataset Replay Control State
  const [datasets, setDatasets] = useState([])
  const [selectedDataset, setSelectedDataset] = useState('elliptic_bitcoin')
  const [selectedCount, setSelectedCount] = useState(100)
  const [selectedSpeed, setSelectedSpeed] = useState(1.0)
  const [replayStatus, setReplayStatus] = useState(null)
  
  const ws = useRef(null)

  useEffect(() => {
    connectWs()
    loadInitialTransactions()
    loadDatasets()
    
    const statusInterval = setInterval(fetchReplayStatus, 1000)

    return () => {
      if (ws.current) ws.current.close()
      clearInterval(statusInterval)
    }
  }, [])

  const loadInitialTransactions = async () => {
    try {
      const recent = await api.recentTransactions(100)
      if (Array.isArray(recent)) {
        setTransactions(recent)
      }
    } catch (e) {
      console.error('Failed to load initial transactions', e)
    }
  }

  const loadDatasets = async () => {
    try {
      const ds = await api.listDatasets()
      setDatasets(ds)
    } catch (e) {
      console.error('Failed to load datasets', e)
    }
  }

  const fetchReplayStatus = async () => {
    try {
      const st = await api.datasetReplayStatus()
      setReplayStatus(st)
    } catch (e) {
      // ignore offline errors silently
    }
  }

  const connectWs = () => {
    const socket = new WebSocket('ws://localhost:8000/dashboard/live')
    
    socket.onopen = () => setConnected(true)
    socket.onclose = () => {
      setConnected(false)
      setTimeout(connectWs, 3000)
    }
    
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'new_transactions') {
        setTransactions(prev => {
          const newTxs = msg.data.filter(t => !prev.find(p => p.transaction_id === t.transaction_id))
          return [...newTxs, ...prev].slice(0, 100)
        })
      }
    }
    ws.current = socket
  }

  // Demo actions
  const startDemo = async () => {
    try {
      await fetch('http://localhost:8000/demo/start', { method: 'POST' })
    } catch (e) { console.error(e) }
  }

  const stopDemo = async () => {
    try {
      await fetch('http://localhost:8000/demo/stop', { method: 'POST' })
    } catch (e) { console.error(e) }
  }

  // Dataset Replay actions
  const startDatasetReplay = async () => {
    try {
      await api.startDatasetReplay({
        dataset_id: selectedDataset,
        count: Number(selectedCount),
        speed: Number(selectedSpeed)
      })
      fetchReplayStatus()
    } catch (e) {
      alert(`Error starting replay: ${e.message}`)
    }
  }

  const stopDatasetReplay = async () => {
    try {
      await api.stopDatasetReplay()
      fetchReplayStatus()
    } catch (e) { console.error(e) }
  }

  const resetDatasetReplay = async () => {
    try {
      await api.resetDatasetReplay()
      fetchReplayStatus()
    } catch (e) { console.error(e) }
  }

  const isReplaying = Boolean(replayStatus?.running)
  const perf = replayStatus?.performance_metrics || {}

  return (
    <div className="page-stack">
      <section className="hero-row">
        <div>
          <div className="section-kicker" style={{ color: connected ? 'var(--approved)' : 'var(--high)' }}>
            ● {connected ? 'STREAM CONNECTED' : 'DISCONNECTED'}
          </div>
          <h1>Live Transaction Monitor</h1>
          <p>Watch transactions stream through the full NexusGuard pipeline in real-time.</p>
        </div>
      </section>

      {/* INGESTION MODE SELECTOR */}
      <section className="panel" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Ingestion Mode</span>
            <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
              <button 
                className={`button ${mode === 'DATASET_REPLAY' ? 'primary' : 'ghost'}`}
                onClick={() => setMode('DATASET_REPLAY')}
                style={mode === 'DATASET_REPLAY' ? { background: 'var(--blue)', color: 'white' } : {}}
              >
                📊 REAL DATASET REPLAY
              </button>
              <button 
                className={`button ${mode === 'DEMO' ? 'primary' : 'ghost'}`}
                onClick={() => setMode('DEMO')}
                style={mode === 'DEMO' ? { background: 'var(--blue)', color: 'white' } : {}}
              >
                ⚡ SYNTHETIC DEMO MODE
              </button>
              <button 
                className={`button ${mode === 'LIVE_API' ? 'primary' : 'ghost'}`}
                onClick={() => setMode('LIVE_API')}
                style={mode === 'LIVE_API' ? { background: 'var(--blue)', color: 'white' } : {}}
              >
                🌐 LIVE API INGESTION
              </button>
            </div>
          </div>

          {/* DEMO MODE CONTROLS */}
          {mode === 'DEMO' && (
            <div style={{ display: 'flex', gap: '10px' }}>
              <button className="button" onClick={startDemo} style={{ background: 'var(--blue)', color: 'white' }}>
                <Play size={16} /> START DEMO
              </button>
              <button className="button" onClick={stopDemo} style={{ background: 'var(--panel-bg)', border: '1px solid var(--border)' }}>
                <Square size={16} /> STOP DEMO
              </button>
            </div>
          )}

          {/* LIVE API INGESTION INFO */}
          {mode === 'LIVE_API' && (
            <div style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>
              POST transactions to <code>http://localhost:8000/transactions/publish</code>
            </div>
          )}
        </div>

        {/* DATASET REPLAY CONTROLS */}
        {mode === 'DATASET_REPLAY' && (
          <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', alignItems: 'end' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>HISTORICAL DATASET</label>
              <select 
                value={selectedDataset} 
                onChange={e => setSelectedDataset(e.target.value)}
                disabled={isReplaying}
                style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
              >
                {datasets.map(ds => (
                  <option key={ds.id} value={ds.id}>{ds.name} ({ds.chain})</option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>TRANSACTIONS TO REPLAY</label>
              <select 
                value={selectedCount} 
                onChange={e => setSelectedCount(e.target.value)}
                disabled={isReplaying}
                style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
              >
                <option value={50}>50 Transactions</option>
                <option value={100}>100 Transactions</option>
                <option value={250}>250 Transactions</option>
                <option value={500}>500 Transactions</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>REPLAY SPEED</label>
              <select 
                value={selectedSpeed} 
                onChange={e => setSelectedSpeed(e.target.value)}
                disabled={isReplaying}
                style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
              >
                <option value={0.5}>0.5 tx / sec (Slow)</option>
                <option value={1.0}>1.0 tx / sec (Normal)</option>
                <option value={2.0}>2.0 tx / sec (Fast)</option>
                <option value={5.0}>5.0 tx / sec (Rapid)</option>
              </select>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button 
                className="button" 
                onClick={startDatasetReplay}
                disabled={isReplaying}
                style={{ background: 'var(--blue)', color: 'white', flex: 1 }}
              >
                <Play size={16} /> START REPLAY
              </button>
              <button 
                className="button" 
                onClick={stopDatasetReplay}
                disabled={!isReplaying}
                style={{ background: 'var(--panel-bg)', border: '1px solid var(--border)' }}
              >
                <Square size={16} /> STOP
              </button>
              <button 
                className="button" 
                onClick={resetDatasetReplay}
                style={{ background: 'var(--panel-bg)', border: '1px solid var(--border)' }}
              >
                <RotateCcw size={16} /> RESET
              </button>
            </div>
          </div>
        )}

        {/* PROGRESS BAR & LIVE STATUS */}
        {mode === 'DATASET_REPLAY' && replayStatus && (
          <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
              <span>Replay Progress: <strong>{replayStatus.processed || 0} / {replayStatus.total_selected || selectedCount}</strong> ({replayStatus.replay_speed_tx_per_sec || selectedSpeed} tx/sec)</span>
              <span>Dataset: <strong>{replayStatus.dataset_name}</strong></span>
            </div>
            <div style={{ width: '100%', height: '8px', background: 'var(--bg)', borderRadius: '4px', overflow: 'hidden' }}>
              <div 
                style={{ 
                  width: `${Math.min(100, (Number(replayStatus.processed || 0) / Number(replayStatus.total_selected || 1)) * 100)}%`, 
                  height: '100%', 
                  background: isReplaying ? 'var(--blue)' : 'var(--approved)', 
                  transition: 'width 0.3s ease' 
                }} 
              />
            </div>
          </div>
        )}
      </section>

      {/* REPLAY SUMMARY & GROUND TRUTH METRICS */}
      {mode === 'DATASET_REPLAY' && replayStatus && (replayStatus.processed > 0) && (
        <section className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          <div className="stat-card">
            <label><Activity size={14}/> Replay Progress</label>
            <div className="value">{replayStatus.processed} / {replayStatus.total_selected}</div>
            <div className="stat-helper">Transactions replayed</div>
          </div>
          <div className="stat-card">
            <label><Zap size={14}/> Avg Latency</label>
            <div className="value">{replayStatus.average_latency_ms} ms</div>
            <div className="stat-helper">Measured pipeline latency</div>
          </div>
          <div className="stat-card">
            <label><CheckCircle2 size={14}/> Approved</label>
            <div className="value" style={{ color: 'var(--approved)' }}>{replayStatus.approved}</div>
            <div className="stat-helper">Low risk decisions</div>
          </div>
          <div className="stat-card">
            <label><AlertTriangle size={14}/> Review</label>
            <div className="value" style={{ color: 'var(--medium)' }}>{replayStatus.review}</div>
            <div className="stat-helper">Medium risk decisions</div>
          </div>
          <div className="stat-card">
            <label><ShieldX size={14}/> Blocked</label>
            <div className="value" style={{ color: 'var(--high)' }}>{replayStatus.blocked}</div>
            <div className="stat-helper">High risk decisions</div>
          </div>
          <div className="stat-card">
            <label>📊 Model Accuracy</label>
            <div className="value">{(Number(perf.accuracy || 0) * 100).toFixed(1)}%</div>
            <div className="stat-helper">Vs ground truth labels</div>
          </div>
        </section>
      )}

      {/* LIVE TRANSACTION TABLE */}
      <section className="panel">
        <div className="panel-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2>NEXUSGUARD — LIVE TRANSACTION MONITOR</h2>
            <span>Processed live backend results with real-time risk scores and decisions</span>
          </div>
        </div>

        <div className="table-wrap compact">
          <table>
            <thead>
              <tr>
                <th>Nexus TX ID</th>
                <th>Source TX ID</th>
                <th>Time</th>
                <th>Sender</th>
                <th>Receiver</th>
                <th>Amount</th>
                <th>Risk Score</th>
                <th>Decision</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map(tx => (
                <tr key={tx.transaction_id} className="live-row">
                  <td>
                    <Link className="table-link" to={`/transactions/${encodeURIComponent(tx.transaction_id)}`}>
                      {tx.transaction_id}
                    </Link>
                  </td>
                  <td className="muted" style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                    {tx.source_transaction_id ? tx.source_transaction_id.substring(0, 14) + '...' : '-'}
                  </td>
                  <td>{formatTime(tx.timestamp)}</td>
                  <td className="muted" style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                    {(tx.sender || tx.account_id || '-').substring(0, 12)}...
                  </td>
                  <td className="muted" style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                    {(tx.receiver || '-').substring(0, 12)}...
                  </td>
                  <td>{formatMoney(tx.amount || tx.transaction_value)}</td>
                  <td>{Number(tx.risk_score || tx.final_risk_score || 0).toFixed(1)}%</td>
                  <td><DecisionBadge value={tx.decision || tx.final_decision} /></td>
                  <td className="muted">{tx.latency_ms ? `${tx.latency_ms} ms` : '—'}</td>
                </tr>
              ))}
              {transactions.length === 0 && (
                <tr>
                  <td colSpan="9" style={{ textAlign: 'center', padding: '40px' }}>
                    <div className="muted">Waiting for transactions from the backend pipeline...</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
