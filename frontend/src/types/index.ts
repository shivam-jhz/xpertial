export type RunStatus = 'running' | 'completed' | 'failed' | 'stopped';
export type AlertLevel = 'warning' | 'critical';
export type InsightSeverity = 'critical' | 'warning' | 'info' | 'positive';
export type InsightCategory = 'waste' | 'bottleneck' | 'stability' | 'cost' | 'positive';
export type LossTrend = 'improving' | 'plateau' | 'diverging' | 'unknown';
export type BottleneckType = 'data_pipeline' | 'cpu_bound' | 'io_bound' | 'gpu_underutilized' | 'normal';

export interface Run {
  run_id: string;
  name: string;
  status: RunStatus;
  tags: Record<string, string> | null;
  gpu_cost_per_hour: number;
  started_at: string;
  ended_at: string | null;
  total_cost_usd: number | null;
  total_steps: number | null;
  final_loss: number | null;
  efficiency_grade: string | null;
  efficiency_score: number | null;
  avg_gpu_util: number | null;
  wasted_cost_usd: number | null;
  last_checkpoint_step: number | null;
  bottleneck: string | null;
}

export interface InsightCard {
  id: string;
  db_id?: number;
  category: InsightCategory;
  severity: InsightSeverity;
  title: string;
  body: string;
  action: string;
  metric_ref: number | null;
  metric_unit: string;
  dismissed: boolean;
  created_at?: string;
}

export interface EfficiencySnapshot {
  step: number;
  time: string;
  gpu_idle_pct: number;
  wasted_cost_usd: number;
  wasted_cost_inr: number;
  bottleneck: BottleneckType;
  bottleneck_detail: string;
  avg_step_time_ms: number;
  step_time_cv: number;
  loss_trend: LossTrend;
  stall_detected: boolean;
  efficiency_score: number;
  efficiency_grade: string;
  loss_plateau_steps: number;
}

export interface RunEnvironment {
  framework: string;
  framework_version: string;
  cloud_provider: string;
  instance_type: string;
  num_gpus: number;
  gpu_names: string[];
  python_version: string;
  cuda_version: string;
  distributed: boolean;
  world_size: number;
  hostname: string;
}

export interface RunSummary {
  run_id: string;
  name: string;
  total_cost_usd: number;
  total_steps: number;
  final_loss: number | null;
  avg_gpu_util: number;
  avg_gpu_idle: number;
  avg_step_time_ms: number;
  efficiency_score: number;
  efficiency_grade: string;
  wasted_cost_usd: number;
  duration_hrs: number;
  bottleneck: string;
}

export interface ComparisonResult {
  runs: RunSummary[];
  winner_id: string;
  winner_name: string;
  insights: string[];
  cost_diff_pct: number;
  loss_diff_pct: number;
  grade_comparison: string;
}

export interface LiveGpuMetric {
  device_index: number;
  device_name: string;
  utilization_pct: number;
  memory_used_mb: number;
  memory_total_mb: number;
  memory_pct: number;
  temperature_c: number;
  power_draw_w: number;
}

export interface CostSnapshot {
  elapsed_secs: number;
  burn_rate_per_hour: number;
  cost_so_far_usd: number;
  projected_total_usd: number | null;
  num_gpus: number;
}

export interface LiveUpdate {
  type: 'metrics' | 'step' | 'insights';
  run_id: string;
  ts: number;
  gpus?: LiveGpuMetric[];
  system?: { cpu_util_pct: number; ram_pct: number; ram_used_mb: number; ram_total_mb: number } | null;
  cost?: CostSnapshot | null;
  step?: { step: number; loss: number | null; step_time_ms: number; tokens_per_sec: number | null; learning_rate: number | null } | null;
  efficiency?: Partial<EfficiencySnapshot> | null;
  insights?: InsightCard[];
  alerts?: { level: string; message: string }[];
}

export interface Alert {
  id: number;
  run_id: string;
  created_at: string;
  level: AlertLevel;
  alert_type: string;
  message: string;
  acknowledged: boolean;
}

export interface ChartPoint { t: number; v: number }
