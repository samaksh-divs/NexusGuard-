export default function DecisionBadge({ value }) {
  const normalized = String(value || 'UNKNOWN').toUpperCase()
  const label = normalized === 'APPROVE' ? 'ALLOW' : normalized === 'BLOCK' ? 'BLOCKED' : normalized
  const cls = normalized === 'APPROVE' ? 'approved' : normalized === 'BLOCK' ? 'blocked' : normalized.toLowerCase()
  return <span className={`badge decision-${cls}`}>{label}</span>
}
