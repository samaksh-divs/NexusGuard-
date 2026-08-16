import { NavLink } from 'react-router-dom'
import { Activity, BarChart3, LayoutDashboard, ShieldAlert, Users, WalletCards } from 'lucide-react'

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/transactions', label: 'Transactions', icon: WalletCards },
  { to: '/analytics', label: 'Risk Analytics', icon: BarChart3 },
  { to: '/accounts', label: 'Suspicious Accounts', icon: Users },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><ShieldAlert size={22} /></div>
        <div>
          <div className="brand-title">NexusGuard</div>
          <div className="brand-subtitle">Fraud & Risk Intelligence</div>
        </div>
      </div>

      <nav className="nav-list">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="system-pill"><Activity size={15} /> Monitoring active</div>
        <div className="phase-label">NexusGuard Phase 8</div>
      </div>
    </aside>
  )
}
