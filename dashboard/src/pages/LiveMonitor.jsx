import { useEffect, useState, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Play, Square, RotateCcw, Activity, Database, Server, Zap, CheckCircle2, AlertTriangle, ShieldX } from 'lucide-react'
import DecisionBadge from '../components/DecisionBadge'
import { api, API_BASE_URL } from '../api/nexusguardApi'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

function formatMoney(value) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value || 0))
}

function formatAssetAmount(value, symbol) {
  if (value == null || !Number.isFinite(Number(value))) return '—'

  const amount = Number(value).toLocaleString('en-US', { maximumFractionDigits: 8 })
  return `${amount}${symbol ? ` ${symbol}` : ''}`
}

function formatTransactionAmount(transaction) {
  if (transaction.source_dataset === 'Mempool.space') {
    return transaction.bitcoin_amount == null
      ? formatMoney(transaction.amount)
      : formatAssetAmount(transaction.bitcoin_amount, 'BTC')
  }

  return formatAssetAmount(
    transaction.amount ?? transaction.transaction_value,
    transaction.symbol,
  )
}

function formatTimestamp(value) {
  if (!value) return '—'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    fractionalSecondDigits: 3,
  }).formatToParts(date)

  const day = parts.find((part) => part.type === 'day')?.value ?? '00'
  const month = parts.find((part) => part.type === 'month')?.value ?? 'Jan'
  const year = parts.find((part) => part.type === 'year')?.value ?? '2000'
  const hour = parts.find((part) => part.type === 'hour')?.value ?? '00'
  const minute = parts.find((part) => part.type === 'minute')?.value ?? '00'
  const second = parts.find((part) => part.type === 'second')?.value ?? '00'
  const fractional = parts.find((part) => part.type === 'fractionalSecond')?.value ?? String(date.getMilliseconds()).padStart(3, '0')

  return `${day} ${month} ${year}, ${hour}:${minute}:${second}.${fractional} IST`
}

function displayMetric(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${(Number(value) * 100).toFixed(1)}%`
}

function displayTableMetric(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }

  return `${(Number(value) * 100).toFixed(1)}%`
}

function titleCase(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

export default function LiveMonitor() {
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState([])
  const [connected, setConnected] = useState(false)
  const [dataVariety, setDataVariety] = useState('batch')
  const [datasetAnalysis, setDatasetAnalysis] = useState(null)
  const [streamError, setStreamError] = useState('')
  const [mempoolStatus, setMempoolStatus] = useState('DISCONNECTED')
  const [replayError, setReplayError] = useState('')

  const [datasets, setDatasets] = useState([])
  const [selectedDataset, setSelectedDataset] = useState('elliptic_bitcoin')
  const [selectedCount, setSelectedCount] = useState(100)
  const [selectedSpeed, setSelectedSpeed] = useState(1.0)
  const [replayStatus, setReplayStatus] = useState(null)

  const ws = useRef(null)
  const reconnectTimer = useRef(null)
  const mempoolSocket = useRef(null)
  const mempoolReconnectTimer = useRef(null)
  const seenMempoolTransactions = useRef(new Set())
  const wsBaseUrl = API_BASE_URL.replace(/^http/, 'ws')

  useEffect(() => {
    let active = true
    const connect = () => {
      if (!active) return
      const socket = new WebSocket(`${wsBaseUrl}/dashboard/live`)
      socket.onopen = () => active && setConnected(true)
      socket.onclose = () => {
        if (active) {
          setConnected(false)
          reconnectTimer.current = setTimeout(connect, 3000)
        }
      }
      socket.onerror = () => socket.close()
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.type === 'new_transactions') {
          setTransactions((prev) => {
            const newTxs = msg.data.filter((transaction) => !prev.find((item) => item.transaction_id === transaction.transaction_id))
            return [...newTxs, ...prev].slice(0, 100)
          })
        }
      }
      ws.current = socket
    }

    connect()
    loadInitialTransactions()
    loadDatasets()

    const statusInterval = setInterval(fetchReplayStatus, 2000)

    return () => {
      active = false
      clearTimeout(reconnectTimer.current)
      if (ws.current) ws.current.close()
      clearInterval(statusInterval)
    }
  }, [])

  useEffect(() => {
    if (dataVariety !== 'streaming') {
      setMempoolStatus('DISCONNECTED')
      return undefined
    }

    let active = true
    let socket = null
    let cachedPricePromise = null
    const pendingTxids = []
    let activeProcessors = 0
    const maxProcessors = 4
    setStreamError('')
    setMempoolStatus('CONNECTING...')

    const fetchJson = async (url) => {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`Mempool.space returned HTTP ${response.status}`)
      }
      return response.json()
    }

    const getBitcoinPrice = () => {
      if (!cachedPricePromise) {
        cachedPricePromise = fetchJson('https://mempool.space/api/v1/prices')
          .then((prices) => {
            const price = Number(prices.USD)
            if (!Number.isFinite(price) || price <= 0) {
              throw new Error('Mempool.space did not return a valid BTC/USD price')
            }
            return price
          })
          .catch((error) => {
            cachedPricePromise = null
            throw error
          })
      }
      return cachedPricePromise
    }

    const processMempoolTransaction = async (txid) => {
      let lastError
      for (let attempt = 0; attempt < 3; attempt += 1) {
        if (!active) {
          seenMempoolTransactions.current.delete(txid)
          return
        }
        try {
          const [transaction, priceUsd] = await Promise.all([
            fetchJson(`https://mempool.space/api/tx/${encodeURIComponent(txid)}`),
            getBitcoinPrice(),
          ])
          const outputs = Array.isArray(transaction.vout) ? transaction.vout : []
          const outputSats = outputs.reduce((total, output) => {
            const value = Number(output.value)
            return total + (Number.isFinite(value) && value > 0 ? value : 0)
          }, 0)
          const bitcoinAmount = outputSats / 1e8

          const inputs = Array.isArray(transaction.vin) ? transaction.vin : []
          const sender = inputs
            .map((input) => input.prevout?.scriptpubkey_address)
            .find((address) => typeof address === 'string' && address.length > 0) || null
          const receiver = outputs
            .map((output) => output.scriptpubkey_address)
            .find((address) => typeof address === 'string' && address.length > 0) || null
          const observedAt = new Date().toISOString()
          const blockTime = Number(transaction.status?.block_time)
          const timestamp = Number.isFinite(blockTime) && blockTime > 0
            ? new Date(blockTime * 1000).toISOString()
            : observedAt

          await api.publishTransaction({
            transaction_id: txid,
            source_transaction_id: txid,
            source_dataset: 'Mempool.space',
            timestamp,
            mempool_observed_at: observedAt,
            symbol: 'BTC',
            chain: 'Bitcoin',
            network: 'Bitcoin Mainnet',
            account_id: sender || txid,
            sender,
            receiver,
            bitcoin_amount: bitcoinAmount,
            amount: bitcoinAmount * priceUsd,
            price: priceUsd,
            quantity: bitcoinAmount,
            fee: Number(transaction.fee || 0) / 1e8,
            fee_sats: Number(transaction.fee || 0),
            status: 'received',
            ingestion_mode: 'MEMPOOL_STREAM',
            mempool_status: transaction.status || null,
            vin: inputs,
            vout: outputs,
          })
          return
        } catch (error) {
          lastError = error
          if (attempt < 2 && active) {
            await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
          }
        }
      }
      seenMempoolTransactions.current.delete(txid)
      if (active) setStreamError(`Could not process Mempool transaction ${txid} after 3 attempts: ${lastError.message}`)
    }

    const drainQueue = () => {
      while (active && activeProcessors < maxProcessors && pendingTxids.length > 0) {
        const txid = pendingTxids.shift()
        activeProcessors += 1
        processMempoolTransaction(txid).finally(() => {
          activeProcessors -= 1
          drainQueue()
        })
      }
    }

    const connect = () => {
      if (!active) return
      setMempoolStatus('CONNECTING...')
      try {
        socket = new WebSocket('wss://mempool.space/api/v1/ws')
      } catch (error) {
        setStreamError(`Could not connect to Mempool.space: ${error.message}`)
        setMempoolStatus('RECONNECTING...')
        mempoolReconnectTimer.current = setTimeout(connect, 3000)
        return
      }
      mempoolSocket.current = socket

      socket.onopen = () => {
        if (!active) return socket.close()
        socket.send(JSON.stringify({ 'track-mempool': true }))
        setMempoolStatus('LIVE')
        setStreamError('')
      }
      socket.onmessage = (event) => {
        let message
        try {
          message = JSON.parse(event.data)
        } catch (error) {
          setStreamError(`Invalid message from Mempool.space: ${error.message}`)
          return
        }
        const mempoolEvent = message['track-mempool']
        const transactionUpdates = message['mempool-transactions']
        const txids = Array.isArray(transactionUpdates?.added)
          ? transactionUpdates.added.map((transaction) => transaction?.txid)
          : [
              typeof message.txid === 'string'
                ? message.txid
                : typeof mempoolEvent?.txid === 'string'
                  ? mempoolEvent.txid
                  : typeof message.data?.txid === 'string'
                    ? message.data.txid
                    : null,
            ]

        for (const txid of txids) {
          if (typeof txid !== 'string' || seenMempoolTransactions.current.has(txid)) continue
          if (pendingTxids.length >= 1000) {
            setStreamError('Mempool processing queue is full; incoming transactions are being rejected instead of silently dropped.')
            break
          }
          seenMempoolTransactions.current.add(txid)
          pendingTxids.push(txid)
        }
        drainQueue()
      }
      socket.onerror = () => {
        if (active) setStreamError('Mempool.space WebSocket reported a connection error.')
        socket.close()
      }
      socket.onclose = () => {
        if (!active) return
        setMempoolStatus('RECONNECTING...')
        setStreamError('Mempool.space disconnected; reconnecting automatically.')
        mempoolReconnectTimer.current = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      active = false
      clearTimeout(mempoolReconnectTimer.current)
      if (socket) {
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        socket.close(1000, 'Leaving Mempool streaming mode')
      }
      mempoolSocket.current = null
      pendingTxids.length = 0
    }
  }, [dataVariety])

  useEffect(() => {
    setReplayStatus(null)
    setReplayError('')
    if (dataVariety === 'batch') {
      fetchDatasetAnalysis(selectedDataset)
    }
  }, [selectedDataset, dataVariety])

  const loadInitialTransactions = async () => {
    try {
      const recent = await api.recentTransactions(100)
      if (Array.isArray(recent)) {
        const mempoolTransactions = recent.filter((transaction) => transaction.source_dataset === 'Mempool.space')
        mempoolTransactions.forEach((transaction) => seenMempoolTransactions.current.add(transaction.transaction_id))
        setTransactions(mempoolTransactions)
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

  const fetchDatasetAnalysis = async (datasetId = selectedDataset) => {
    try {
      const analysis = await api.datasetAnalysis(datasetId)
      setDatasetAnalysis(analysis)
    } catch (e) {
      console.error('Failed to load dataset analysis', e)
      setDatasetAnalysis(null)
    }
  }

  const fetchReplayStatus = async () => {
    try {
      const st = await api.datasetReplayStatus()
      setReplayStatus(st)
      setReplayError('')
    } catch (error) {
      setReplayError(`Could not read batch replay status: ${error.message}`)
    }
  }

  const startDatasetReplay = async () => {
    try {
      await api.startDatasetReplay({
        dataset_id: selectedDataset,
        count: Number(selectedCount),
        speed: Number(selectedSpeed),
      })
      await fetchReplayStatus()
    } catch (error) {
      setReplayError(`Could not start batch replay: ${error.message}`)
    }
  }

  const stopDatasetReplay = async () => {
    try {
      await api.stopDatasetReplay()
      fetchReplayStatus()
    } catch (error) {
      setReplayError(`Could not stop batch replay: ${error.message}`)
    }
  }

  const resetDatasetReplay = async () => {
    try {
      await api.resetDatasetReplay()
      fetchReplayStatus()
    } catch (error) {
      setReplayError(`Could not reset batch replay: ${error.message}`)
    }
  }

  const isReplaying = Boolean(replayStatus?.running)
  const isReplayActive = isReplaying || replayStatus?.replay_state === 'PROCESSING'
  const perf = replayStatus?.performance_metrics || {}
  const previewColumns = datasetAnalysis?.columns ?? []
  const evaluationRows = datasetAnalysis?.evaluation ?? []
  const modelComparison = replayStatus?.model_comparison ?? evaluationRows
  const batchTransactions = replayStatus?.processed_transactions ?? []
  const chartData = modelComparison
    .filter((row) => row.accuracy !== null && row.accuracy !== undefined)
    .map((row) => ({
      name: row.model,
      Accuracy: Number(row.accuracy ?? 0),
      Precision: Number(row.precision ?? 0),
      Recall: Number(row.recall ?? 0),
      'F1 Score': Number(row.f1_score ?? 0),
    }))

  return (
    <div className="page-stack">
      <section className="hero-row">
        <div>
          <div className="section-kicker" style={{ color: dataVariety === 'streaming' ? (mempoolStatus === 'LIVE' ? 'var(--approved)' : 'var(--high)') : (connected ? 'var(--approved)' : 'var(--high)') }}>
            ● {dataVariety === 'streaming' ? mempoolStatus : connected ? 'DASHBOARD CONNECTED' : 'DASHBOARD DISCONNECTED'}
          </div>
          <h1>Live Transaction Monitor</h1>
          <p>Watch transactions move through the NexusGuard pipeline in real time.</p>
        </div>
      </section>

      <section className="panel" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Data Variety</span>
            <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
              <button
                className={`button ${dataVariety === 'batch' ? 'primary' : 'ghost'}`}
                onClick={() => setDataVariety('batch')}
                style={dataVariety === 'batch' ? { background: 'var(--blue)', color: 'white' } : {}}
              >
                Batch
              </button>
              <button
                className={`button ${dataVariety === 'streaming' ? 'primary' : 'ghost'}`}
                onClick={() => setDataVariety('streaming')}
                style={dataVariety === 'streaming' ? { background: 'var(--blue)', color: 'white' } : {}}
              >
                Streaming
              </button>
            </div>
          </div>
        </div>

        {dataVariety === 'batch' && (
          <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', alignItems: 'end' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>Dataset</label>
                <select
                  value={selectedDataset}
                  onChange={(event) => setSelectedDataset(event.target.value)}
                  disabled={isReplayActive}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
                >
                  {datasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>{dataset.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>Transactions to replay</label>
                <select
                  value={selectedCount}
                  onChange={(event) => setSelectedCount(event.target.value)}
                  disabled={isReplayActive}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
                >
                  <option value={50}>50 transactions</option>
                  <option value={100}>100 transactions</option>
                  <option value={250}>250 transactions</option>
                  <option value={500}>500 transactions</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--muted)', marginBottom: '4px' }}>Replay speed</label>
                <select
                  value={selectedSpeed}
                  onChange={(event) => setSelectedSpeed(event.target.value)}
                  disabled={isReplayActive}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--fg)' }}
                >
                  <option value={0.5}>0.5 tx / sec</option>
                  <option value={1.0}>1.0 tx / sec</option>
                  <option value={2.0}>2.0 tx / sec</option>
                  <option value={5.0}>5.0 tx / sec</option>
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

            {replayStatus && (
              <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
                  <span>Replay Status: <strong>{replayStatus.replay_state || (isReplaying ? 'RUNNING' : 'IDLE')}</strong></span>
                  <span>Processed: <strong>{replayStatus.processed || 0} / {replayStatus.total_selected || selectedCount}</strong></span>
                  <span>Dataset: <strong>{replayStatus.dataset_name}</strong></span>
                </div>
                <div style={{ width: '100%', height: '8px', background: 'var(--bg)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${Math.min(100, (Number(replayStatus.processed || 0) / Number(replayStatus.total_selected || 1)) * 100)}%`,
                      height: '100%',
                      background: isReplaying ? 'var(--blue)' : 'var(--approved)',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
                {replayStatus.replay_error && (
                  <div role="alert" style={{ marginTop: '8px', color: 'var(--high)' }}>
                    Replay failed: {replayStatus.replay_error}
                  </div>
                )}
              </div>
            )}
            {replayError && <div role="alert" style={{ marginTop: '10px', color: 'var(--high)' }}>{replayError}</div>}
          </div>
        )}

        {dataVariety === 'batch' && replayStatus?.total_selected > 0 && (
          <div className="panel" style={{ marginTop: '16px', padding: '16px' }}>
            <div className="panel-heading">
              <div>
                <h2>Batch evaluation results</h2>
                <span>
                  {replayStatus.evaluation_samples || 0} processed, labeled transactions compared with ground truth
                </span>
              </div>
            </div>
            <div className="stats-grid four">
              {[
                ['Accuracy', perf.accuracy],
                ['Precision', perf.precision],
                ['Recall', perf.recall],
                ['F1 score', perf.f1_score],
              ].map(([label, value]) => (
                <div className="stat-card" key={label}>
                  <div className="stat-label">{label}</div>
                  <div className="stat-value">{displayMetric(value)}</div>
                </div>
              ))}
            </div>
            <div className="stat-helper" style={{ marginTop: '10px' }}>
              Metrics use only transactions actually processed by the backend. REVIEW and BLOCK count as predicted fraud;
              dataset ground-truth labels are used only for this post-processing evaluation.
            </div>
          </div>
        )}

        {dataVariety === 'batch' && batchTransactions.length > 0 && (
          <section className="panel" style={{ marginTop: '16px' }}>
            <div className="panel-heading">
              <div>
                <h2>Processed batch transactions</h2>
                <span>Select any result to inspect its decision, risk reasons, model outputs and source label.</span>
              </div>
            </div>
            <div className="table-wrap compact">
              <table>
                <thead>
                  <tr>
                    <th>Transaction ID</th>
                    <th>Time</th>
                    <th>Amount</th>
                    <th>Risk score</th>
                    <th>Decision</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {batchTransactions.map((tx) => (
                    <tr
                      key={tx.transaction_id}
                      className="live-row"
                      tabIndex={0}
                      role="link"
                      onClick={() => navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)
                        }
                      }}
                    >
                      <td>{tx.transaction_id}</td>
                      <td>{formatTimestamp(tx.timestamp)}</td>
                      <td>{formatAssetAmount(tx.amount, tx.symbol)}</td>
                      <td>{tx.risk_score == null ? '—' : `${Number(tx.risk_score).toFixed(1)}%`}</td>
                      <td><DecisionBadge value={tx.decision || tx.final_decision} /></td>
                      <td>{(tx.reasons || []).join('; ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {dataVariety === 'batch' && datasetAnalysis && (
          <div style={{ marginTop: '20px' }}>
            <div className="panel-heading" style={{ marginBottom: '12px' }}>
              <div>
                <h2>Dataset information</h2>
                <span>Historical batch dataset loaded from the actual CSV</span>
              </div>
            </div>

            <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
              <div className="stat-card">
                <label><Database size={14} /> Dataset name</label>
                <div className="value">{datasetAnalysis.dataset_name}</div>
                <div className="stat-helper">Loaded dataset</div>
              </div>
              <div className="stat-card">
                <label><Server size={14} /> CSV filename</label>
                <div className="value" style={{ fontSize: '0.9rem' }}>{datasetAnalysis.csv_filename}</div>
                <div className="stat-helper">Source file</div>
              </div>
              <div className="stat-card">
                <label><Activity size={14} /> Total records</label>
                <div className="value">{datasetAnalysis.total_records}</div>
                <div className="stat-helper">Rows in the CSV</div>
              </div>
              <div className="stat-card">
                <label><CheckCircle2 size={14} /> Legitimate records</label>
                <div className="value" style={{ color: 'var(--approved)' }}>{datasetAnalysis.legitimate_records}</div>
                <div className="stat-helper">Ground-truth = 0</div>
              </div>
              <div className="stat-card">
                <label><ShieldX size={14} /> Fraudulent records</label>
                <div className="value" style={{ color: 'var(--high)' }}>{datasetAnalysis.fraudulent_records}</div>
                <div className="stat-helper">Ground-truth = 1</div>
              </div>
              <div className="stat-card">
                <label><AlertTriangle size={14} /> Unknown records</label>
                <div className="value">{datasetAnalysis.unknown_records}</div>
                <div className="stat-helper">Unlabelled rows</div>
              </div>
            </div>

            <div style={{ marginTop: '20px' }}>
              <div className="panel-heading" style={{ marginBottom: '8px' }}>
                <div>
                  <h2>CSV preview</h2>
                  <span>Actual records from the loaded historical dataset</span>
                </div>
              </div>
              <div className="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      {previewColumns.map((column) => (
                        <th key={column}>{column === 'ground_truth_label' ? 'Ground Truth' : titleCase(column)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(datasetAnalysis.preview_rows || []).map((row, index) => (
                      <tr key={`${row[Object.keys(row)[0]] || index}`}>
                        {previewColumns.map((column) => (
                          <td key={`${column}-${index}`} style={{ whiteSpace: 'nowrap' }}>
                            {row[column] ?? '—'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ marginTop: '20px', display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px' }}>
              <div>
                <div className="panel-heading" style={{ marginBottom: '8px' }}>
                  <div>
                    <h2>Label distribution</h2>
                    <span>Ground-truth distribution in the loaded dataset</span>
                  </div>
                </div>
                <div className="table-wrap compact">
                  <table>
                    <thead>
                      <tr>
                        <th>Label</th>
                        <th>Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(datasetAnalysis.label_distribution || []).map((entry) => (
                        <tr key={entry.name}>
                          <td>{entry.name}</td>
                          <td>{entry.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div>
                <div className="panel-heading" style={{ marginBottom: '8px' }}>
                  <div>
                    <h2>Feature information</h2>
                    <span>Relevant feature columns in the CSV</span>
                  </div>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {(datasetAnalysis.feature_columns || []).slice(0, 12).map((column) => (
                    <span key={column} style={{ padding: '6px 10px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: '999px', fontSize: '0.75rem' }}>
                      {titleCase(column)}
                    </span>
                  ))}
                  {!(datasetAnalysis.feature_columns || []).length && (
                    <div className="muted">No additional feature columns detected in this dataset.</div>
                  )}
                </div>
              </div>
            </div>

            <div style={{ marginTop: '20px' }}>
              <div className="panel-heading" style={{ marginBottom: '8px' }}>
                <div>
                  <h2>Model comparison</h2>
                  <span>Random Forest, XGBoost and LSTM predictions compared against processed batch labels</span>
                </div>
              </div>

              <div className="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Accuracy</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>F1 Score</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelComparison.map((row) => (
                      <tr key={row.model}>
                        <td>{row.model}</td>
                        <td>{displayMetric(row.accuracy)}</td>
                        <td>{displayTableMetric(row.precision)}</td>
                        <td>{displayTableMetric(row.recall)}</td>
                        <td>{displayTableMetric(row.f1_score)}</td>
                        <td>{row.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {chartData.length > 0 ? (
                <div style={{ marginTop: '20px', height: '260px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="name" stroke="var(--muted)" />
                      <YAxis stroke="var(--muted)" tickFormatter={(value) => `${value * 100}%`} />
                      <Tooltip formatter={(value) => `${Number(value * 100).toFixed(1)}%`} />
                      <Bar dataKey="Accuracy" fill="#6ea8fe" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="Precision" fill="#4cc9f0" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="Recall" fill="#f4a261" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="F1 Score" fill="#2ec4b6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div style={{ marginTop: '20px', padding: '16px', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--muted)' }}>
                  Individual model metrics are unavailable until the required model artifacts are present and the batch
                  has produced labeled predictions. The pipeline-level metrics above are measured from actual backend
                  decisions.
                </div>
              )}
            </div>
          </div>
        )}

        {dataVariety === 'streaming' && (
          <div style={{ marginTop: '20px' }}>
            <div className="panel-heading" style={{ marginBottom: '12px' }}>
              <div>
                <h2>Live Bitcoin mempool stream</h2>
                <span>Actual unconfirmed transactions are screened by NexusGuard through the existing RabbitMQ worker pipeline.</span>
              </div>
            </div>

            <div className="stats-grid four" style={{ marginBottom: '16px' }}>
              {[
                ['Data Source', 'Mempool.space'],
                ['Network', 'Bitcoin Mainnet'],
                ['Protocol', 'WebSocket'],
                ['Stream', 'Live Bitcoin Mempool Transactions'],
              ].map(([label, value]) => (
                <div className="stat-card" key={label}>
                  <div className="stat-label">{label}</div>
                  <div className="stat-value" style={{ fontSize: '1rem' }}>{value}</div>
                </div>
              ))}
            </div>

            <div style={{ marginBottom: '12px', color: mempoolStatus === 'LIVE' ? 'var(--approved)' : 'var(--muted)', fontWeight: 700 }}>
              {mempoolStatus}
            </div>
            {streamError && <div role="alert" style={{ marginBottom: '12px', color: 'var(--high)' }}>{streamError}</div>}
            <p style={{ color: 'var(--muted)' }}>
              Mempool.space transactions enter the NexusGuard API and continue through RabbitMQ, the transaction worker,
              and MongoDB. The USD value for existing value-based risk rules uses Mempool.space BTC/USD spot pricing.
            </p>
            <div style={{ display: 'flex', gap: '16px', marginBottom: '16px' }}>
              <a href="https://mempool.space/" target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', textDecoration: 'underline' }}>
                Open Mempool.space
              </a>
              <a href="https://mempool.space/docs/api/websocket" target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', textDecoration: 'underline' }}>
                WebSocket API documentation
              </a>
              <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', textDecoration: 'underline' }}>
                NexusGuard API
              </a>
            </div>

            <div className="panel-heading" style={{ marginBottom: '8px' }}>
              <div>
                <h2>Live transactions</h2>
                <span>Only actual Mempool.space transactions with completed NexusGuard processing are shown.</span>
              </div>
            </div>
            <div className="table-wrap compact">
              <table>
                <thead>
                  <tr>
                    <th>Transaction ID</th>
                    <th>Time</th>
                    <th>Bitcoin Amount</th>
                    <th>Risk Score</th>
                    <th>Decision</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions
                    .filter((transaction) => transaction.source_dataset === 'Mempool.space')
                    .map((tx) => (
                      <tr
                        key={tx.transaction_id}
                        className="live-row"
                        tabIndex={0}
                        role="link"
                        onClick={() => navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)
                          }
                        }}
                      >
                        <td>
                          <Link className="table-link" to={`/transactions/${encodeURIComponent(tx.transaction_id)}`} onClick={(event) => event.stopPropagation()}>
                            {tx.transaction_id}
                          </Link>
                        </td>
                        <td>{formatTimestamp(tx.mempool_observed_at || tx.timestamp)}</td>
                        <td>{tx.bitcoin_amount == null ? '—' : `${Number(tx.bitcoin_amount).toFixed(8)} BTC`}</td>
                        <td>{tx.risk_score == null ? '—' : `${Number(tx.risk_score).toFixed(1)}%`}</td>
                        <td><DecisionBadge value={tx.decision || tx.final_decision} /></td>
                        <td>{(tx.risk_reasons || tx.fraud_reasons || []).join('; ') || '—'}</td>
                      </tr>
                    ))}
                  {!transactions.some((transaction) => transaction.source_dataset === 'Mempool.space') && (
                    <tr>
                      <td colSpan="6" style={{ textAlign: 'center', padding: '40px' }}>
                        <div className="muted">
                          {mempoolStatus === 'LIVE'
                            ? 'Connected; waiting for actual Mempool.space transactions to be processed.'
                            : 'No Mempool transactions have completed processing.'}
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {dataVariety === 'batch' && <section className="panel">
        <div className="panel-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2>NEXUSGUARD — LIVE TRANSACTION MONITOR</h2>
            <span>Processed batch backend results</span>
          </div>
        </div>

        <div className="table-wrap compact">
          <table>
            <thead>
              <tr>
                <th>Transaction ID</th>
                <th>Time</th>
                <th>Amount</th>
                <th>Risk Score</th>
                <th>Decision</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx) => (
                <tr
                  key={tx.transaction_id}
                  className="live-row"
                  tabIndex={0}
                  role="link"
                  onClick={() => navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      navigate(`/transactions/${encodeURIComponent(tx.transaction_id)}`)
                    }
                  }}
                >
                  <td>
                      <Link className="table-link" to={`/transactions/${encodeURIComponent(tx.transaction_id)}`} onClick={(event) => event.stopPropagation()}>
                        {tx.transaction_id}
                      </Link>
                  </td>
                  <td>{formatTimestamp(tx.timestamp)}</td>
                  <td>{formatTransactionAmount(tx)}</td>
                  <td>{tx.risk_score == null && tx.final_risk_score == null
                    ? '—'
                    : `${Number(tx.risk_score ?? tx.final_risk_score).toFixed(1)}%`}</td>
                  <td><DecisionBadge value={tx.decision || tx.final_decision} /></td>
                  <td>{(tx.risk_reasons || tx.fraud_reasons || []).join('; ') || '—'}</td>
                </tr>
              ))}
              {transactions.length === 0 && (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', padding: '40px' }}>
                    <div className="muted">Waiting for transactions from the backend pipeline...</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>}
    </div>
  )
}
