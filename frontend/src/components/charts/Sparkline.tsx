import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

interface Point { t: number; v: number }

interface SparkProps {
  data: Point[];
  color?: string;
  label?: string;
  unit?: string;
  domain?: [number | 'auto', number | 'auto'];
  height?: number;
  showGrid?: boolean;
  xLabel?: string;
}

const TT = {
  background: 'var(--s1)', border: '1px solid var(--bd)', borderRadius: '3px',
  fontSize: '10px', fontFamily: 'var(--mono)', color: 'var(--tp)', padding: '3px 7px',
};

export function Sparkline({ data, color = 'var(--amber)', label = '', unit = '', domain = ['auto', 'auto'], height = 72, showGrid = false, xLabel = 'step' }: SparkProps) {
  if (!data.length) return (
    <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <span style={{ color: 'var(--tm)', fontSize: 10, fontFamily: 'var(--mono)' }}>awaiting data…</span>
    </div>
  );
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 2, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`g${label}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.22} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {showGrid && <CartesianGrid strokeDasharray="2 4" stroke="var(--bd)" />}
        <XAxis dataKey="t" tick={{ fontSize: 8, fontFamily: 'var(--mono)', fill: 'var(--tm)' }} axisLine={false} tickLine={false} tickCount={4} />
        <YAxis domain={domain} tick={{ fontSize: 8, fontFamily: 'var(--mono)', fill: 'var(--tm)' }} axisLine={false} tickLine={false} tickCount={3} width={32} />
        <Tooltip contentStyle={TT} formatter={(v: number) => [`${v.toFixed(3)}${unit}`, label]} labelFormatter={l => `${xLabel}: ${l}`} itemStyle={{ color }} cursor={{ stroke: 'var(--bd)', strokeWidth: 1 }} />
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={`url(#g${label})`} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
