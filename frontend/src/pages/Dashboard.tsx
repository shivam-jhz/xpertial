import { useCallback, useEffect, useMemo, useState } from 'react';
import { GpuPanel, TrainingPanel, SystemPanel } from '../components/panels/MetricsPanels';
import { CostPanelV2 } from '../components/panels/CostPanelV2';
import { InsightsPanel } from '../components/panels/InsightsPanel';
import { EfficiencyPanel } from '../components/panels/EfficiencyPanel';
import { CompareModal } from '../components/panels/CompareModal';
import { useWebSocket } from '../hooks/useWebSocket';
import { api } from '../lib/api';
import type { Alert, InsightCard, Run } from '../types';

const STATUS_COLOR: Record<string, string> = {
  running: 'var(--green)', completed: 'var(--blue)', failed: 'var(--red)', stopped: 'var(--tm)',
};
const STATUS_ICON: Record<string, string> = {
  running: '●', completed: '◆', failed: '✕', stopped: '■',
};

function relTime(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  const s = Math.floor(d / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}
function fmtDur(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  return `${m}m ${sec}s`;
}

const GRADE_CLR: Record<string, string> = { A: '#3ecf72', B: '#4aa8f0', C: '#f0a840', D: '#f08040', F: '#f05050' };

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [insights, setInsights] = useState<InsightCard[]>([]);
  const [stepHistory, setStepHistory] = useState<any[]>([]);
  const [gpuHistory, setGpuHistory] = useState<any[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [compareOpen, setCompareOpen] = useState(false);
  const [tab, setTab] = useState<'live' | 'history'>('live');

  // Load runs list
  const loadRuns = useCallback(async () => {
    try { setRuns(await api.runs.list(30)); } catch {}
  }, []);

  useEffect(() => { loadRuns(); const t = setInterval(loadRuns, 10000); return () => clearInterval(t); }, [loadRuns]);

  // Auto-select first running run
  useEffect(() => {
    if (selectedId) return;
    const r = runs.find(r => r.status === 'running') ?? runs[0];
    if (r) setSelectedId(r.run_id);
  }, [runs, selectedId]);

  // Load run detail
  useEffect(() => {
    if (!selectedId) return;
    (async () => {
      try {
        const [r, s, g, a, ins] = await Promise.all([
          api.runs.get(selectedId),
          api.runs.stepMetrics(selectedId),
          api.runs.gpuMetrics(selectedId),
          api.runs.alerts(selectedId),
          api.insights.list(selectedId).catch(() => []),
        ]);
        setRun(r); setStepHistory(s); setGpuHistory(g); setAlerts(a); setInsights(ins);
      } catch {}
    })();
  }, [selectedId]);

  // Elapsed timer
  useEffect(() => {
    if (run?.status !== 'running') return;
    const tick = () => setElapsed((Date.now() - new Date(run.started_at).getTime()) / 1000);
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [run]);

  const live = useWebSocket(run?.status === 'running' ? selectedId : null);

  // Merge live insights with REST
  const activeInsights = useMemo(() => {
    if (live.insights.length > 0) return live.insights;
    return insights;
  }, [live.insights, insights]);

  // Historical loss/step data for charts
  const histLoss = useMemo(() =>
    stepHistory.filter(p => p.loss != null).map(p => ({ t: p.step, v: p.loss })),
    [stepHistory]);

  const mergedLoss = useMemo(() => {
    if (!live.lossHistory.length) return histLoss;
    const seen = new Set(live.lossHistory.map(p => p.t));
    return [...histLoss.filter(p => !seen.has(p.t)), ...live.lossHistory].slice(-300);
  }, [histLoss, live.lossHistory]);

  const stepTimeHistory = useMemo(() =>
    stepHistory.filter(p => p.step_time_ms != null).map(p => ({ t: p.step, v: p.step_time_ms })),
    [stepHistory]);

  const isLive = run?.status === 'running';
  const wsStatus = isLive ? live.status : 'disconnected';
  const efficiency = live.efficiency ?? null;

  const dismissInsight = useCallback(async (id: string) => {
    if (!selectedId) return;
    await api.insights.dismiss(selectedId, id).catch(() => {});
    setInsights(prev => prev.map(i => i.id === id ? { ...i, dismissed: true } : i));
  }, [selectedId]);

  const WS_CLR: Record<string, string> = { connected: 'var(--green)', connecting: 'var(--amber)', disconnected: 'var(--tm)', error: 'var(--red)' };

  return (
    <div className="layout">
      {/* Topbar */}
      <header className="topbar">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <rect x="1" y="1" width="9" height="9" fill="var(--amber)" rx="1"/>
            <rect x="12" y="1" width="9" height="9" fill="var(--amber)" opacity=".4" rx="1"/>
            <rect x="1" y="12" width="9" height="9" fill="var(--amber)" opacity=".4" rx="1"/>
            <rect x="12" y="12" width="9" height="9" fill="var(--amber)" rx="1"/>
          </svg>
          <span className="brand-name">XPERTIAL</span>
          <span className="brand-tag">TRAINING INTELLIGENCE</span>
        </div>

        <div className="topbar-run">
          {run ? (
            <>
              <span style={{ color: STATUS_COLOR[run.status], fontSize: 9 }}>{STATUS_ICON[run.status]}</span>
              <span className="run-title">{run.name}</span>
              {isLive && <span className="run-elapsed">{fmtDur(elapsed)}</span>}
              {run.efficiency_grade && (
                <span className="grade-badge" style={{ color: GRADE_CLR[run.efficiency_grade] ?? 'var(--ts)', borderColor: GRADE_CLR[run.efficiency_grade] ?? 'var(--bd)' }}>
                  {run.efficiency_grade}
                </span>
              )}
            </>
          ) : <span style={{ color: 'var(--tm)', fontSize: 11 }}>Select a run →</span>}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginLeft: 'auto' }}>
          <button className="btn-ghost" onClick={() => setCompareOpen(true)}>⟺ Compare</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 5, height: 5, borderRadius: '50%', background: WS_CLR[wsStatus], boxShadow: wsStatus === 'connected' ? `0 0 5px ${WS_CLR.connected}` : 'none' }} />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--tm)', letterSpacing: '.1em' }}>{wsStatus.toUpperCase()}</span>
          </div>
        </div>
      </header>

      <div className="layout__body">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-hdr">
            <span>RUNS</span>
            <div style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--amber)', animation: 'blink 1.4s ease-in-out infinite' }} />
          </div>
          <div className="run-items">
            {runs.map(r => (
              <button key={r.run_id} className={`run-item ${r.run_id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(r.run_id)}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ color: STATUS_COLOR[r.status], fontSize: 8 }}>{STATUS_ICON[r.status]}</span>
                  <span className="ri-name">{r.name}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--tm)' }}>{relTime(r.started_at)}</span>
                  {r.status === 'running'
                    ? <span style={{ fontFamily: 'var(--mono)', fontSize: 7, color: 'var(--green)', border: '1px solid var(--green)', padding: '0 3px', borderRadius: 2 }}>LIVE</span>
                    : r.total_cost_usd != null ? <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--amber)' }}>${r.total_cost_usd.toFixed(2)}</span> : null}
                </div>
                {r.efficiency_grade && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    {r.final_loss != null && <span style={{ fontFamily: 'var(--mono)', fontSize: 8, color: 'var(--tm)' }}>loss {r.final_loss.toExponential(2)}</span>}
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: GRADE_CLR[r.efficiency_grade] ?? 'var(--ts)', marginLeft: 'auto' }}>{r.efficiency_grade}</span>
                  </div>
                )}
              </button>
            ))}
          </div>
        </aside>

        {/* Main */}
        <main className="dashboard">
          {!selectedId ? (
            <div className="splash">
              <div style={{ fontSize: 48, color: 'var(--bd)' }}>⬡</div>
              <div className="splash-title">NO RUN SELECTED</div>
              <div className="splash-sub">Install the agent and start a training run</div>
              <div className="splash-code">
                <pre>{`pip install xpertial\n\n# Add to your training script:\nfrom xpertial import monitor\nmonitor.start(api_key='YOUR_KEY')\n\n# That's it. Everything is auto-detected.`}</pre>
              </div>
              <div className="splash-code" style={{ marginTop: 8 }}>
                <pre>{`# Verify setup:\nxpertial init`}</pre>
              </div>
            </div>
          ) : (
            <>
              {/* Tab bar */}
              <div className="tab-bar">
                <button className={`tab ${tab === 'live' ? 'active' : ''}`} onClick={() => setTab('live')}>
                  {isLive && <span style={{ color: 'var(--green)', fontSize: 7, marginRight: 5 }}>●</span>}Live
                </button>
                <button className={`tab ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>History</button>
              </div>

              <div className="dashboard__grid">
                {/* Left: GPU + System */}
                <div className="col">
                  <GpuPanel gpus={live.gpus} utilHistory={live.gpuUtilHistory} />
                  <SystemPanel system={live.system} />
                </div>

                {/* Center: Training + Insights */}
                <div className="col">
                  <TrainingPanel step={live.step} lossHistory={mergedLoss} stepTimeHistory={live.stepTimeHistory.length ? live.stepTimeHistory : stepTimeHistory} />
                  <InsightsPanel insights={activeInsights} onDismiss={dismissInsight} />
                </div>

                {/* Right: Efficiency + Cost + Alerts */}
                <div className="col">
                  <EfficiencyPanel efficiency={efficiency} wastedInr={efficiency?.wasted_cost_inr} />
                  <CostPanelV2
                    cost={live.cost}
                    run={run}
                    gpuIdlePct={efficiency?.gpu_idle_pct}
                    wastedCostInr={efficiency?.wasted_cost_inr}
                  />
                  {alerts.filter(a => !a.acknowledged).length > 0 && (
                    <div className="panel">
                      <div className="panel__title">
                        ALERTS
                        <span style={{ marginLeft: 6, background: 'var(--red)', color: '#fff', fontFamily: 'var(--mono)', fontSize: 8, padding: '1px 5px', borderRadius: 2 }}>
                          {alerts.filter(a => !a.acknowledged).length}
                        </span>
                      </div>
                      <div className="panel__body" style={{ padding: 0 }}>
                        {alerts.filter(a => !a.acknowledged).slice(0, 5).map(a => (
                          <div key={a.id} style={{ padding: '7px 10px', borderBottom: '1px solid var(--bd)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                            <div style={{ width: 5, height: 5, borderRadius: '50%', marginTop: 4, flexShrink: 0, background: a.level === 'critical' ? 'var(--red)' : 'var(--amber)', boxShadow: `0 0 4px ${a.level === 'critical' ? 'var(--red)' : 'var(--amber)'}` }} />
                            <span style={{ fontFamily: 'var(--body)', fontSize: 10, color: 'var(--ts)', lineHeight: 1.4 }}>{a.message}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      {compareOpen && <CompareModal runs={runs} onClose={() => setCompareOpen(false)} />}
    </div>
  );
}
