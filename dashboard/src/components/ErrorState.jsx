export default function ErrorState({ message, onRetry }) {
  return (
    <div className="state-card error-state">
      <strong>Unable to load dashboard data</strong>
      <div>{message}</div>
      {onRetry && <button className="primary-button" onClick={onRetry}>Retry</button>}
    </div>
  )
}
