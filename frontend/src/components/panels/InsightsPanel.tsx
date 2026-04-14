import { useState } from 'react';
import type { InsightCard } from '../../types';

interface Props {
  insights: InsightCard[];
  onDismiss?: (id: string) => void;
}

const SEV_CONFIG = {
  critical: { dot: '#f05050', badge: '#f05050', text: 'CRITICAL', bg: 'rgba(240,80,80,0.06)' },
  warning:  { dot: '#f0a840', badge: '#f0a840', text: 'WARNING',  bg: 'rgba(240,168,64,0.06)' },
  info:     { dot: '#4aa8f0', badge: '#4aa8f0', text: 'INFO',     bg: 'rgba(74,168,240,0.06)' },
  positive: { dot: '#3ecf72', badge: '#3ecf72', text: 'OK',       bg: 'rgba(62,207,114,0.06)' },
};

const CAT_ICONS: Record<string, string> = {
  waste:       '⚡',
  bottleneck:  '🔍',
  stability:   '⚠',
  cost:        '₹',
  positive:    '✓',
};

export function InsightsPanel({ insights, onDismiss }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const active = insights.filter(i => !i.dismissed);

  const critCount = active.filter(i => i.severity === 'critical').length;
  const warnCount = active.filter(i => i.severity === 'warning').length;

  return (
    <div className="panel insights-panel">
      <div className="panel__title">
        INSIGHTS
        <div style={{ display: 'flex', gap: 4, marginLeft: 6 }}>
          {critCount > 0 && <span className="insight-count crit">{critCount}</span>}
          {warnCount > 0 && <span className="insight-count warn">{warnCount}</span>}
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--tm)', letterSpacing: '.06em' }}>
          {active.length} active
        </span>
      </div>
      <div className="panel__body" style={{ padding: 0 }}>
        {active.length === 0 && (
          <div style={{ padding: '16px 12px', display: 'flex', alignItems: 'center', gap: 8, color: 'var(--tm)', fontFamily: 'var(--mono)', fontSize: 10 }}>
            <span style={{ color: 'var(--green)', fontSize: 14 }}>✓</span>
            No issues detected — training looks healthy
          </div>
        )}
        {active.map(card => {
          const cfg = SEV_CONFIG[card.severity] ?? SEV_CONFIG.info;
          const open = expanded === card.id;
          return (
            <div
              key={card.id}
              className="insight-card"
              style={{ background: open ? cfg.bg : 'transparent', borderLeft: `2px solid ${cfg.dot}` }}
            >
              <div
                className="insight-card__header"
                onClick={() => setExpanded(open ? null : card.id)}
                style={{ cursor: 'pointer' }}
              >
                <span className="insight-icon">{CAT_ICONS[card.category] ?? '•'}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <span className="insight-sev" style={{ color: cfg.dot }}>{cfg.text}</span>
                    {card.metric_ref != null && (
                      <span className="insight-metric" style={{ color: cfg.dot }}>
                        {card.metric_ref.toFixed(card.metric_unit === '%' ? 0 : 2)}{card.metric_unit}
                      </span>
                    )}
                  </div>
                  <div className="insight-title">{card.title}</div>
                </div>
                <span className="insight-chevron" style={{ transform: open ? 'rotate(90deg)' : 'none' }}>›</span>
              </div>

              {open && (
                <div className="insight-card__body">
                  <p className="insight-body-text">{card.body}</p>
                  <div className="insight-action">
                    <span className="action-label">ACTION</span>
                    <span className="action-text">{card.action}</span>
                  </div>
                  {onDismiss && card.severity !== 'critical' && (
                    <button className="insight-dismiss" onClick={(e) => { e.stopPropagation(); onDismiss(card.id); }}>
                      Dismiss
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
