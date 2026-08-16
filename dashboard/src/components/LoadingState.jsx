export default function LoadingState({ label = 'Loading NexusGuard data…' }) {
  return <div className="state-card"><div className="spinner" /><div>{label}</div></div>
}
