import type {
  Alert, ComparisonResult, EfficiencySnapshot,
  InsightCard, Run, RunEnvironment,
} from '../types';

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json();
}

async function patch<T>(path: string, body: unknown = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status}`);
  return res.json();
}

export const api = {
  runs: {
    list: (limit = 50): Promise<Run[]> => get(`/api/v1/runs?limit=${limit}`),
    get: (id: string): Promise<Run> => get(`/api/v1/runs/${id}`),
    gpuMetrics: (id: string, limit = 300) => get<any[]>(`/api/v1/runs/${id}/gpu_metrics?limit=${limit}`),
    stepMetrics: (id: string, limit = 500) => get<any[]>(`/api/v1/runs/${id}/step_metrics?limit=${limit}`),
    alerts: (id: string): Promise<Alert[]> => get(`/api/v1/runs/${id}/alerts`),
    ackAlert: (id: string, alertId: number) => patch(`/api/v1/runs/${id}/alerts/${alertId}/ack`),
    environment: (id: string): Promise<RunEnvironment> => get(`/api/v1/runs/${id}/environment`),
  },
  insights: {
    list: (runId: string): Promise<InsightCard[]> => get(`/api/v1/runs/${runId}/insights`),
    dismiss: (runId: string, insightId: string) =>
      patch(`/api/v1/runs/${runId}/insights/${insightId}/dismiss`),
    efficiencyHistory: (runId: string): Promise<EfficiencySnapshot[]> =>
      get(`/api/v1/runs/${runId}/efficiency`),
    latestEfficiency: (runId: string): Promise<EfficiencySnapshot> =>
      get(`/api/v1/runs/${runId}/efficiency/latest`),
  },
  compare: (runIds: string[]): Promise<ComparisonResult> =>
    post('/api/v1/compare', { run_ids: runIds }),
};

export function wsUrl(runId: string): string {
  const base = (import.meta.env.VITE_WS_URL ?? BASE).replace(/^http/, 'ws');
  return `${base}/ws/${runId}`;
}
