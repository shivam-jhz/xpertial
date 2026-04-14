import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { ComparisonResult, Run } from '../../types';

interface Props {
  runs: Run[];
  onClose: () => void;
}

const GRADE_COLOR: Record<string, string> = {
  A: '#3ecf72', B: '#4aa8f0', C: '#f0a840', D: '#f08040', F: '#f05050',
};

export function CompareModal({ runs, onClose }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (id: string) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 4 ? [...prev, id] : prev
    );
  };

  const runComparison = async () => {
    if (selected.length < 2) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.compare(selected);
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <span className="modal__title">COMPARE RUNS</span>
          <button className="modal__close" onClick={onClose}>✕</button>
        </div>

        <div className="modal__body">
          {!result ? (
            <>
              <p className="modal__hint">Select 2–4 runs to compare</p>
              <div className="compare-run-list">
                {runs.map(run => {
                  const sel = selected.includes(run.run_id);
                  return (
                    <div
                      key={run.run_id}
                      className={`compare-run-item ${sel ? 'selected' : ''}`}
                      onClick={() => toggle(run.run_id)}
                    >
                      <div className="cri-check">{sel ? '✓' : ''}</div>
                      <div style={{ flex: 1 }}>
                        <div className="cri-name">{run.name}</div>
                        <div className="cri-meta">
                          <span>{run.status}</span>
                          {run.total_cost_usd != null && <span>${run.total_cost_usd.toFixed(2)}</span>}
                          {run.final_loss != null && <span>loss {run.final_loss.toExponential(2)}</span>}
                        </div>
                      </div>
                      {run.efficiency_grade && (
                        <span className="cri-grade" style={{ color: GRADE_COLOR[run.efficiency_grade] ?? '#7e95aa' }}>
                          {run.efficiency_grade}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="modal__actions">
                <button
                  className="btn-primary"
                  disabled={selected.length < 2 || loading}
                  onClick={runComparison}
                >
                  {loading ? 'Analysing…' : `Compare ${selected.length} runs`}
                </button>
              </div>
              {error && <div className="modal__error">{error}</div>}
            </>
          ) : (
            <ComparisonView result={result} onBack={() => setResult(null)} />
          )}
        </div>
      </div>
    </div>
  );
}

function ComparisonView({ result, onBack }: { result: ComparisonResult; onBack: () => void }) {
  const maxCost = Math.max(...result.runs.map(r => r.total_cost_usd));
  const maxUtil = Math.max(...result.runs.map(r => r.avg_gpu_util));

  return (
    <div className="comparison-view">
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>← Back</button>

      {/* Winner banner */}
      <div className="winner-banner">
        <span className="winner-crown">🏆</span>
        <div>
          <div className="winner-name">{result.winner_name}</div>
          <div className="winner-sub">Most efficient run · Grade {result.runs.find(r => r.run_id === result.winner_id)?.efficiency_grade}</div>
        </div>
        <div className="winner-grades">{result.grade_comparison}</div>
      </div>

      {/* Run table */}
      <div className="compare-table">
        <div className="ct-header">
          <span>RUN</span>
          <span>COST</span>
          <span>GPU UTIL</span>
          <span>FINAL LOSS</span>
          <span>GRADE</span>
        </div>
        {result.runs.map(run => {
          const isWinner = run.run_id === result.winner_id;
          const gc = GRADE_COLOR[run.efficiency_grade] ?? '#7e95aa';
          return (
            <div key={run.run_id} className={`ct-row ${isWinner ? 'ct-row--winner' : ''}`}>
              <span className="ct-name">{run.name}{isWinner && <span className="ct-best">BEST</span>}</span>
              <div>
                <div className="ct-val">${run.total_cost_usd.toFixed(2)}</div>
                <div className="ct-bar">
                  <div className="ct-bar-fill" style={{ width: `${(run.total_cost_usd / maxCost) * 100}%`, background: isWinner ? '#3ecf72' : '#f0a840' }} />
                </div>
              </div>
              <div>
                <div className="ct-val">{run.avg_gpu_util.toFixed(0)}%</div>
                <div className="ct-bar">
                  <div className="ct-bar-fill" style={{ width: `${run.avg_gpu_util}%`, background: '#4aa8f0' }} />
                </div>
              </div>
              <span className="ct-val">{run.final_loss != null ? run.final_loss.toExponential(2) : '—'}</span>
              <span style={{ color: gc, fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 16 }}>{run.efficiency_grade}</span>
            </div>
          );
        })}
      </div>

      {/* Insights */}
      <div className="compare-insights">
        <div className="ci-title">KEY FINDINGS</div>
        {result.insights.map((insight, i) => (
          <div key={i} className="ci-item">
            <span className="ci-bullet">›</span>
            <span>{insight}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
