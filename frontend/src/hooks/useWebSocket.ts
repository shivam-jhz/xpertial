import { useCallback, useEffect, useRef, useState } from 'react';
import { wsUrl } from '../lib/api';
import type { CostSnapshot, InsightCard, LiveGpuMetric, LiveUpdate } from '../types';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

const HISTORY = 300;

export interface LiveState {
  status: WsStatus;
  gpus: LiveGpuMetric[];
  system: { cpu_util_pct: number; ram_pct: number; ram_used_mb: number; ram_total_mb: number } | null;
  step: { step: number; loss: number | null; step_time_ms: number; tokens_per_sec: number | null; learning_rate: number | null } | null;
  cost: CostSnapshot | null;
  insights: InsightCard[];
  efficiency: any | null;
  recentAlerts: { level: string; message: string }[];
  lossHistory: { t: number; v: number }[];
  gpuUtilHistory: { t: number; v: number }[][];
  efficiencyHistory: { t: number; score: number; idle: number }[];
  lastUpdate: number;
}

const init = (): LiveState => ({
  status: 'connecting', gpus: [], system: null, step: null, cost: null,
  insights: [], efficiency: null, recentAlerts: [],
  lossHistory: [], gpuUtilHistory: [], efficiencyHistory: [], lastUpdate: 0,
});

function push<T>(arr: T[], item: T, max = HISTORY): T[] {
  const next = [...arr, item];
  return next.length > max ? next.slice(next.length - max) : next;
}

export function useWebSocket(runId: string | null): LiveState {
  const [state, setState] = useState<LiveState>(init);
  const ws = useRef<WebSocket | null>(null);
  const delay = useRef(2000);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  const connect = useCallback(() => {
    if (!runId || !mounted.current) return;
    setState(s => ({ ...s, status: 'connecting' }));
    const sock = new WebSocket(wsUrl(runId));
    ws.current = sock;

    sock.onopen = () => { if (mounted.current) { delay.current = 2000; setState(s => ({ ...s, status: 'connected' })); } };

    sock.onmessage = ({ data }) => {
      if (!mounted.current) return;
      try {
        const msg: LiveUpdate = JSON.parse(data);
        setState(prev => {
          const next = { ...prev, lastUpdate: Date.now() };

          if (msg.type === 'metrics') {
            if (msg.gpus?.length) {
              next.gpus = msg.gpus;
              while (next.gpuUtilHistory.length < msg.gpus.length) next.gpuUtilHistory = [...next.gpuUtilHistory, []];
              next.gpuUtilHistory = msg.gpus.map((g, i) =>
                push(next.gpuUtilHistory[i] ?? [], { t: msg.ts * 1000, v: g.utilization_pct })
              );
            }
            if (msg.system) next.system = msg.system;
            if (msg.cost) next.cost = msg.cost;
            if (msg.alerts?.length) next.recentAlerts = [...msg.alerts, ...prev.recentAlerts].slice(0, 30);
          }

          if (msg.type === 'step' && msg.step) {
            next.step = msg.step;
            if (msg.step.loss != null) next.lossHistory = push(next.lossHistory, { t: msg.step.step, v: msg.step.loss });
            if (msg.alerts?.length) next.recentAlerts = [...msg.alerts, ...prev.recentAlerts].slice(0, 30);
          }

          if (msg.type === 'insights') {
            if (msg.efficiency) {
              next.efficiency = msg.efficiency;
              next.efficiencyHistory = push(next.efficiencyHistory, {
                t: msg.ts * 1000,
                score: (msg.efficiency as any).efficiency_score ?? 0,
                idle: (msg.efficiency as any).gpu_idle_pct ?? 0,
              }, 100);
            }
            if (msg.insights?.length) next.insights = msg.insights;
          }

          return next;
        });
      } catch { /* ignore malformed */ }
    };

    sock.onclose = () => {
      if (!mounted.current) return;
      setState(s => ({ ...s, status: 'disconnected' }));
      timer.current = setTimeout(() => { delay.current = Math.min(delay.current * 1.5, 30000); connect(); }, delay.current);
    };
    sock.onerror = () => setState(s => ({ ...s, status: 'error' }));
  }, [runId]);

  useEffect(() => {
    mounted.current = true;
    connect();
    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
      ws.current?.close();
    };
  }, [connect]);

  return state;
}
