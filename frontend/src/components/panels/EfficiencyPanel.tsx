import type { EfficiencySnapshot } from '../../types';

interface Props {
  efficiency: Partial<EfficiencySnapshot> | null;
  wastedInr?: number;
}

const GRADE_COLORS: Record<string, string> = {
  A: '#3ecf72', B: '#4aa8f0', C: '#f0a840', D: '#f08040', F: '#f05050',
};

const BOTTLENECK_LABELS: Record<string, string> = {
  data_pipeline:   'Data Pipeline',
  cpu_bound:       'CPU Bound',
  io_bound:        'I/O Bound',
  gpu_underutilized: 'GPU Underused',
  normal:          'No Bottleneck',
};

const TREND_ICONS: Record<string, string> = {
  improving: '↘',
  plateau:   '→',
  diverging: '↗',
  unknown:   '?',
};

const TREND_COLORS: Record<string, string> = {
  improving: '#3ecf72',
  plateau:   '#f0a840',
  diverging: '#f05050',
  unknown:   '#3f5060',
};

export function EfficiencyPanel({ efficiency, wastedInr }: Props) {
  if (!efficiency) {
    return (
      <div className="panel">
        <div className="panel__title">EFFICIENCY</div>
        <div className="panel__body empty-state">Awaiting efficiency data…</div>
      </div>
    );
  }

  const grade = efficiency.efficiency_grade ?? '?';
  const gradeColor = GRADE_COLORS[grade] ?? '#7e95aa';
  const score = efficiency.efficiency_score ?? 0;
  const idle = efficiency.gpu_idle_pct ?? 0;
  const wasted = efficiency.wasted_cost_usd ?? 0;
  const inr = wastedInr ?? efficiency.wasted_cost_inr ?? 0;
  const bottleneck = efficiency.bottleneck ?? 'normal';
  const trend = efficiency.loss_trend ?? 'unknown';
  const stall = efficiency.stall_detected ?? false;
  const plateau = efficiency.loss_plateau_steps ?? 0;
  const cv = efficiency.step_time_cv ?? 0;

  return (
    <div className="panel">
      <div className="panel__title">EFFICIENCY</div>
      <div className="panel__body">
        {/* Grade + score */}
        <div className="eff-hero">
          <div className="eff-grade" style={{ color: gradeColor }}>{grade}</div>
          <div className="eff-score-block">
            <div className="eff-score-val" style={{ color: gradeColor }}>{score.toFixed(0)}/100</div>
            <div className="eff-score-lbl">EFFICIENCY SCORE</div>
          </div>
        </div>

        {/* Score bar */}
        <div style={{ marginBottom: 14 }}>
          <div className="eff-bar-track">
            <div className="eff-bar-fill" style={{ width: `${score}%`, background: gradeColor }} />
          </div>
        </div>

        {/* Stats grid */}
        <div className="eff-grid">
          <EffStat label="GPU IDLE" value={`${idle.toFixed(0)}%`}
            color={idle > 30 ? '#f05050' : idle > 15 ? '#f0a840' : '#3ecf72'} />
          <EffStat label="WASTED" value={`₹${inr.toFixed(0)}`}
            sub={`$${wasted.toFixed(2)}`}
            color={wasted > 1 ? '#f05050' : '#f0a840'} />
          <EffStat label="LOSS TREND" value={TREND_ICONS[trend]}
            sub={trend}
            color={TREND_COLORS[trend]} />
          <EffStat label="STEP CV" value={cv.toFixed(2)}
            color={cv > 0.3 ? '#f05050' : cv > 0.15 ? '#f0a840' : '#3ecf72'} />
        </div>

        {/* Bottleneck badge */}
        <div className="bottleneck-badge" data-type={bottleneck}>
          <span className="bn-dot" data-type={bottleneck} />
          <span className="bn-label">
            {BOTTLENECK_LABELS[bottleneck] ?? bottleneck}
          </span>
          {bottleneck !== 'normal' && (
            <span className="bn-tag">BOTTLENECK</span>
          )}
        </div>

        {/* Stall warning */}
        {stall && (
          <div className="stall-banner">
            ⚠ Training stalled — {plateau} steps without improvement
          </div>
        )}

        {/* Detail text */}
        {efficiency.bottleneck_detail && bottleneck !== 'normal' && (
          <div className="bottleneck-detail">{efficiency.bottleneck_detail}</div>
        )}
      </div>
    </div>
  );
}

function EffStat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="eff-stat">
      <div className="eff-stat__lbl">{label}</div>
      <div className="eff-stat__val" style={{ color: color ?? 'var(--tp)' }}>{value}</div>
      {sub && <div className="eff-stat__sub">{sub}</div>}
    </div>
  );
}
