import type { CostSnapshot, Run } from '../../types';

interface Props {
  cost: CostSnapshot | null;
  run: Run | null;
  gpuIdlePct?: number;
  wastedCostInr?: number;
}

const INR_PER_USD = 83;

function fmt(usd: number) {
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 10) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(1)}`;
}
function fmtInr(inr: number) {
  if (inr < 100) return `₹${inr.toFixed(0)}`;
  if (inr < 10000) return `₹${inr.toFixed(0)}`;
  return `₹${(inr / 1000).toFixed(1)}k`;
}
function fmtDur(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function CostPanelV2({ cost, run, gpuIdlePct = 0, wastedCostInr = 0 }: Props) {
  const isLive = run?.status === 'running';
  const costUsd = cost?.cost_so_far_usd ?? run?.total_cost_usd ?? 0;
  const costInr = costUsd * INR_PER_USD;
  const projUsd = cost?.projected_total_usd ?? null;
  const burnRate = cost?.burn_rate_per_hour ?? 0;
  const elapsed = cost?.elapsed_secs ?? 0;
  const progressPct = projUsd && projUsd > 0 ? Math.min((costUsd / projUsd) * 100, 100) : 0;
  const wastedUsd = run?.wasted_cost_usd ?? 0;
  const wastedInr = wastedCostInr || wastedUsd * INR_PER_USD;
  const effectivePct = gpuIdlePct > 0 ? 100 - gpuIdlePct : 100;

  return (
    <div className="panel">
      <div className="panel__title">COST INTELLIGENCE</div>
      <div className="panel__body">
        {/* Hero cost */}
        <div className="cost-hero">
          <div className="cost-usd">{fmt(costUsd)}</div>
          <div className="cost-inr">₹{Math.round(costInr).toLocaleString('en-IN')}</div>
          <div className="cost-lbl">{isLive ? 'BURNED SO FAR' : 'TOTAL COST'}</div>
        </div>

        {/* Burn rate + projection */}
        {isLive && burnRate > 0 && (
          <div className="burn-row">
            <div className="burn-item">
              <div className="burn-val">{fmt(burnRate)}<span>/hr</span></div>
              <div className="burn-lbl">BURN RATE</div>
            </div>
            {projUsd && (
              <div className="burn-item">
                <div className="burn-val" style={{ color: 'var(--amber)' }}>{fmt(projUsd)}</div>
                <div className="burn-lbl">PROJECTED</div>
              </div>
            )}
            <div className="burn-item">
              <div className="burn-val">{fmtDur(elapsed)}</div>
              <div className="burn-lbl">RUNTIME</div>
            </div>
          </div>
        )}

        {/* Spend progress */}
        {projUsd && (
          <div style={{ marginBottom: 14 }}>
            <div className="chart-label" style={{ marginBottom: 5 }}>SPEND PROGRESS</div>
            <div className="prog-track">
              <div className="prog-fill" style={{ width: `${progressPct}%` }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3, fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--tm)' }}>
              <span>{fmt(costUsd)}</span><span>{fmt(projUsd)} projected</span>
            </div>
          </div>
        )}

        {/* Waste breakdown */}
        {(wastedUsd > 0 || gpuIdlePct > 0) && (
          <div className="waste-block">
            <div className="waste-header">
              <span className="waste-icon">⚡</span>
              <span className="waste-title">GPU WASTE</span>
            </div>
            <div className="waste-body">
              <div className="waste-split">
                <div className="waste-col">
                  <div className="waste-val wasted" style={{ color: gpuIdlePct > 30 ? 'var(--red)' : 'var(--amber)' }}>
                    {fmtInr(wastedInr)}
                  </div>
                  <div className="waste-lbl">WASTED</div>
                </div>
                <div className="waste-col">
                  <div className="waste-val effective">
                    {effectivePct.toFixed(0)}%
                  </div>
                  <div className="waste-lbl">EFFECTIVE</div>
                </div>
              </div>
              {/* Effective vs wasted bar */}
              <div className="waste-bar-row">
                <div className="waste-bar-eff" style={{ flex: effectivePct }} />
                <div className="waste-bar-idle" style={{ flex: gpuIdlePct }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3, fontFamily: 'var(--mono)', fontSize: 8 }}>
                <span style={{ color: 'var(--green)' }}>GPU active {effectivePct.toFixed(0)}%</span>
                <span style={{ color: 'var(--red)' }}>Idle {gpuIdlePct.toFixed(0)}%</span>
              </div>
            </div>
          </div>
        )}

        {/* Rate table */}
        <div className="cost-table">
          {run && <CostRow label="GPU rate" value={`${fmt(run.gpu_cost_per_hour)}/GPU/hr`} />}
          {cost && <CostRow label="Active GPUs" value={`${cost.num_gpus}`} />}
          {run?.last_checkpoint_step != null && (
            <CostRow label="Last checkpoint" value={`step ${run.last_checkpoint_step}`} />
          )}
        </div>
      </div>
    </div>
  );
}

function CostRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="cost-row">
      <span className="cr-label">{label}</span>
      <span className="cr-value">{value}</span>
    </div>
  );
}
