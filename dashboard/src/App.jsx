import { useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import TransactionDetails from './pages/TransactionDetails'
import RiskAnalytics from './pages/RiskAnalytics'
import SuspiciousAccounts from './pages/SuspiciousAccounts'
import './styles/nexusguard.css'

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0)
  return <BrowserRouter><div className="app-shell"><Sidebar /><main className="main-shell"><Header onRefresh={() => setRefreshKey(v => v + 1)} /><div className="content"><Routes><Route path="/" element={<Dashboard refreshKey={refreshKey} />} /><Route path="/transactions" element={<Transactions />} /><Route path="/transactions/:transactionId" element={<TransactionDetails />} /><Route path="/analytics" element={<RiskAnalytics />} /><Route path="/accounts" element={<SuspiciousAccounts />} /></Routes></div></main></div></BrowserRouter>
}
