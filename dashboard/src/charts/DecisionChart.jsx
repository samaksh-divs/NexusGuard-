import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

export default function DecisionChart({ summary }) {
  const data = [
    { name: 'Approved', value: summary?.approved || 0 },
    { name: 'Review', value: summary?.review || 0 },
    { name: 'Blocked', value: summary?.blocked || 0 },
  ]

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={82} paddingAngle={4}>
            <Cell fill="var(--approved)" />
            <Cell fill="var(--medium)" />
            <Cell fill="var(--high)" />
          </Pie>
          <Tooltip contentStyle={{ background: '#0c1726', border: '1px solid #1e3046', borderRadius: 10 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
