import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

export default function RiskDistributionChart({ distribution }) {
  const data = [
    { name: 'LOW', value: distribution?.LOW || 0 },
    { name: 'MEDIUM', value: distribution?.MEDIUM || 0 },
    { name: 'HIGH', value: distribution?.HIGH || 0 },
  ]

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={58} outerRadius={84} paddingAngle={4}>
            <Cell fill="var(--low)" />
            <Cell fill="var(--medium)" />
            <Cell fill="var(--high)" />
          </Pie>
          <Tooltip contentStyle={{ background: '#0c1726', border: '1px solid #1e3046', borderRadius: 10 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
