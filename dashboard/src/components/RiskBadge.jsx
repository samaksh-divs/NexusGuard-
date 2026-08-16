export default function RiskBadge({ value }) {
  const normalized = String(value || 'UNKNOWN').toUpperCase()
  return <span className={`badge risk-${normalized.toLowerCase()}`}>{normalized}</span>
}
