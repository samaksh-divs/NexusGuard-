import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export default function ActivityChart({ transactions }) {
  const buckets = new Map()
  for (const tx of transactions || []) {
    const date = new Date(tx.timestamp)
    if (Number.isNaN(date.getTime())) continue
    const key = `${date.getMonth() + 1}/${date.getDate()}`
    buckets.set(key, (buckets.get(key) || 0) + 1)
  }

  const data = [...buckets.entries()].map(([date, count]) => ({ date, count })).slice(-14)

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#17283c" />
          <XAxis dataKey="date" stroke="#7f91a7" />
          <YAxis allowDecimals={false} stroke="#7f91a7" />
          <Tooltip contentStyle={{ background: '#0c1726', border: '1px solid #1e3046', borderRadius: 10 }} />
          <Line type="monotone" dataKey="count" stroke="var(--accent)" strokeWidth={3} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
