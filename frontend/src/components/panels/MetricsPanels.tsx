import { Sparkline } from '../charts/Sparkline';
import { RadialGauge, BarGauge } from '../charts/Gauge';
import type { LiveGpuMetric } from '../../types';

// ── GPU Panel ─────────────────────────────────────────────────────────────────

interface GpuProps {
  gpus: LiveGpuMetric[];
  utilHistory: { t: number; v: number }[][];
}

export function GpuPanel({ gpus, utilHistory }: GpuProps) {
  if (!gpus.length) return (
    <div className="panel"><div className="panel__title">GPU METRICS</div>
      <div className="panel__body empty-state">No GPU — CPU-only or agent not connected</div></div>
  );

  return (
    <div className="panel">
      <div className="panel__title">GPU METRICS — {gpus.length} DEVICE{gpus.length > 1 ? 'S' : ''}</div>
      <div className="panel__body" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        {gpus.map((gpu, i) => (
          <div key={gpu.device_index} className={i < gpus.length - 1 ? 'gpu-device' : ''}>
            <div className="gpu-hdr">
              <span className="gpu-idx">GPU:{gpu.device_index}</span>
              <span className="gpu-nm">{gpu.device_name}</span>
              <span className="gpu-pw">{gpu.power_draw_w.toFixed(0)}W</span>
            </div>
            <div className="gauges">
              <RadialGauge value={gpu.utilization_pct} label="Util" warnAt={30} critAt={10} size={68} />
              <RadialGauge value={gpu.memory_pct} label="VRAM" warnAt={85} critAt={95} size={68} />
              <RadialGauge value={gpu.temperature_c} max={105} label="Temp" unit="°" warnAt={80} critAt={90} size={68} />
            </div>
            <BarGauge
              value={gpu.memory_used_mb} max={gpu.memory_total_mb}
              label="VRAM" warnAt={85} critAt={97}
              formatValue={v => `${(v / 1024).toFixed(1)} GB / ${(gpu.memory_total_mb / 1024).toFixed(0)} GB`}
            />
            <div style={{ marginTop: 8 }}>
              <div className="chart-label">GPU UTIL %</div>
              <Sparkline data={utilHistory[i] ?? []} color="var(--green)" label="util" unit="%" domain={[0, 100]} height={52} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Training Panel ────────────────────────────────────────────────────────────

interface TrainingProps {
  step: { step: number; loss: number | null; step_time_ms: number; tokens_per_sec: number | null; learning_rate: number | null } | null;
  lossHistory: { t: number; v: number }[];
  stepTimeHistory: { t: number; v: number }[];
}

export function TrainingPanel({ step, lossHistory, stepTimeHistory }: TrainingProps) {
  const fmtLoss = (v: number | null | undefined) => v == null ? '—' : v.toExponential(3);
  const fmtNum = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(0)}k` : `${n.toFixed(0)}`;

  return (
    <div className="panel">
      <div className="panel__title">TRAINING METRICS</div>
      <div className="panel__body">
        <div className="kpi-row">
          <KPI label="STEP" value={step ? step.step.toLocaleString() : '—'} />
          <KPI label="LOSS" value={fmtLoss(step?.loss)} color="var(--amber)" />
          <KPI label="STEP" value={step ? `${step.step_time_ms.toFixed(0)}` : '—'} unit="ms" />
          <KPI label="LR" value={step?.learning_rate != null ? step.learning_rate.toExponential(1) : '—'} />
        </div>
        {step?.tokens_per_sec != null && (
          <div className="thr-badge">
            <span>⚡</span>
            <span>{fmtNum(step.tokens_per_sec)} tok/s</span>
          </div>
        )}
        <div className="chart-label">LOSS CURVE</div>
        <Sparkline data={lossHistory} color="var(--amber)" label="loss" height={76} showGrid xLabel="step" />
        <div className="chart-label" style={{ marginTop: 10 }}>STEP TIME (ms)</div>
        <Sparkline data={stepTimeHistory} color="var(--blue)" label="ms" unit="ms" height={52} xLabel="step" />
      </div>
    </div>
  );
}

// ── System Panel ─────────────────────────────────────────────────────────────

interface SysProps {
  system: { cpu_util_pct: number; ram_pct: number; ram_used_mb: number; ram_total_mb: number } | null;
}

export function SystemPanel({ system }: SysProps) {
  return (
    <div className="panel">
      <div className="panel__title">SYSTEM</div>
      <div className="panel__body">
        {!system ? <div className="empty-state">Awaiting…</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <BarGauge value={system.cpu_util_pct} max={100} label="CPU" unit="%" warnAt={85} critAt={95} />
            <BarGauge value={system.ram_used_mb} max={system.ram_total_mb} label="RAM" warnAt={80} critAt={95}
              formatValue={v => `${(v / 1024).toFixed(1)} GB / ${(system.ram_total_mb / 1024).toFixed(0)} GB`} />
          </div>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, unit = '', color }: { label: string; value: string; unit?: string; color?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-l">{label}</div>
      <div className="kpi-v" style={{ color: color ?? 'var(--tp)' }}>{value}<span className="kpi-u">{unit}</span></div>
    </div>
  );
}
