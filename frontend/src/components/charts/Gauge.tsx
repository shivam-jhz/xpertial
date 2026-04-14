// RadialGauge and BarGauge - reused from mlobs, adapted for XPERTIAL

function gc(v: number, warnAt: number, critAt: number) {
  if (critAt < warnAt) { // lower is worse (util)
    if (v <= critAt) return 'var(--red)';
    if (v <= warnAt) return 'var(--amber)';
    return 'var(--green)';
  }
  if (v >= critAt) return 'var(--red)';
  if (v >= warnAt) return 'var(--amber)';
  return 'var(--green)';
}

interface RadialProps { value: number; max?: number; label: string; unit?: string; warnAt?: number; critAt?: number; size?: number }

export function RadialGauge({ value, max = 100, label, unit = '%', warnAt = 80, critAt = 90, size = 72 }: RadialProps) {
  const pct = Math.min(value / max, 1);
  const color = gc(value, warnAt, critAt);
  const cx = size / 2, cy = size / 2, r = size * 0.37, sw = size * 0.08;
  const start = -210, sweep = 240;
  const end = start + sweep * pct;
  function polar(a: number) { const rad = a * Math.PI / 180; return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }; }
  function arc(a1: number, a2: number) { const s = polar(a1), e = polar(a2), large = a2 - a1 > 180 ? 1 : 0; return `M${s.x} ${s.y} A${r} ${r} 0 ${large} 1 ${e.x} ${e.y}`; }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
      <svg width={size} height={size}>
        <path d={arc(start, start + sweep)} fill="none" stroke="var(--s2)" strokeWidth={sw} strokeLinecap="round" />
        {pct > 0 && <path d={arc(start, end)} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />}
        <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="middle" fill={color} fontSize={size * 0.17} fontFamily="var(--mono)" fontWeight="600">{Math.round(value)}{unit}</text>
      </svg>
      <span style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--tm)', letterSpacing: '.08em', textTransform: 'uppercase' }}>{label}</span>
    </div>
  );
}

interface BarProps { value: number; max: number; label: string; unit?: string; warnAt?: number; critAt?: number; formatValue?: (v: number) => string }

export function BarGauge({ value, max, label, unit = '', warnAt = 80, critAt = 95, formatValue }: BarProps) {
  const pct = Math.min((value / max) * 100, 100);
  const color = gc(pct, warnAt, critAt);
  const display = formatValue ? formatValue(value) : `${value.toFixed(1)}${unit}`;
  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ts)' }}>
        <span>{label}</span><span style={{ color }}>{display}</span>
      </div>
      <div style={{ width: '100%', height: 4, background: 'var(--s2)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width .4s ease' }} />
      </div>
    </div>
  );
}
