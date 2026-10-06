import { useEffect, useState } from 'react'
import { Bell, RefreshCw } from 'lucide-react'
import { api } from '../api/nexusguardApi'

export default function Header({ onRefresh }) {
  const [healthy, setHealthy] = useState(null)

  useEffect(() => {
    let mounted = true
    api.health().then((data) => mounted && setHealthy(data?.status === 'healthy')).catch(() => mounted && setHealthy(false))
    return () => { mounted = false }
  }, [])

  return (
    <header className="topbar">
      <div>
        <div className="eyebrow">SECURITY OPERATIONS</div>
        <div className="topbar-title">Fraud Monitoring Center</div>
      </div>
      <div className="topbar-actions">
        <div className={`health-indicator ${healthy === false ? 'offline' : ''}`}>
          <span className="health-dot" />
          {healthy === false ? 'Backend degraded' : healthy === true ? 'Backend healthy' : 'Checking backend'}
        </div>
        <button className="icon-button" title="Refresh dashboard" onClick={onRefresh}><RefreshCw size={17} /></button>
        <div className="icon-button"><Bell size={17} /></div>
      </div>
    </header>
  )
}
