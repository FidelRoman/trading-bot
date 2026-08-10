export interface Prices {
  bid: number;
  ask: number;
  spread_pips: number;
  time: string;
}

export interface Position {
  trade_id: string;
  open_order_id?: string;
  side: "long" | "short";
  units: number;
  open_rate: number;
  open_time: string;
  stop: number;
  limit: number;
  gross_pl?: number;
}

export interface Stats {
  trades: number;
  net_pnl: number;
  win_rate_pct: number;
  profit_factor: number | null;
  total_pips: number;
}

export interface Status {
  running: boolean;
  paused: boolean;
  halted_today: boolean;
  connected: boolean;
  mode: string;
  active_strategy: string;
  account: {
    account_id?: string;
    balance?: number;
    equity?: number;
    usable_margin?: number;
    connection?: string;
  };
  daily_pl_pct: number;
  daily_pl_abs: number;
  max_drawdown_pct: number;
  trades_today: number;
  max_trades_per_day: number;
  open_trade: Record<string, unknown> | null;
  stats: Stats;
  last_candle: string | null;
  net_position?: number;
  active_model?: string | null;
  last_decision?: Decision | null;
}

/* -- FSRPPO ------------------------------------------------------------- */

export interface Decision {
  action: number[];
  target_position: number;
  delta_units: number;
  side: "buy" | "sell" | "hold";
  price: number;
  hursts: number[];
  kept: boolean[];
  discarded_energy: number;
}

export interface FsrPreview {
  ok: boolean;
  error?: string;
  window: number;
  times: string[];
  prices: number[];
  signal: number[];
  imfs: number[][];
  hursts: number[];
  kept: boolean[];
  discarded_energy: number;
}

/** Las siete métricas de la Tabla 2 del paper. */
export interface PaperMetrics {
  crr: number | null;
  arr: number | null;
  avr: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  calmar: number | null;
  sortino: number | null;
  bars?: number;
  trades?: number;
  strategy?: string;
}

export interface TrainingCurvePoint {
  iteration: number;
  mean_reward: number;
  mean_equity: number;
  policy_loss: number;
  value_loss: number;
  entropy: number;
}

export interface TrainingState {
  status: "idle" | "running" | "done" | "error";
  kind?: "training" | "precompute";
  note?: string;
  progress?: number;
  error?: string;
  run_id?: string;
  elapsed_s?: number;
  bars?: number;
  curve?: TrainingCurvePoint[];
  train_metrics?: PaperMetrics;
  test_metrics?: PaperMetrics;
  benchmark_metrics?: PaperMetrics;
  activated?: boolean;
}

export interface ModelRecord {
  run_id: string;
  created_at: string;
  instrument: string;
  timeframe: string;
  train_range: string[];
  test_range: string[];
  fsr_params: Record<string, unknown>;
  ppo_params: Record<string, unknown>;
  env_params: Record<string, unknown>;
  train_metrics: PaperMetrics;
  test_metrics: PaperMetrics;
  benchmark_metrics: PaperMetrics;
  feature_scale?: number;
  is_active?: boolean;
}

export interface InstrumentSpec {
  symbol: string;
  pip: number;
  min_lot: number;
  typical_spread_pips: number;
  quote_currency: string;
}

export interface MarketRankingRow {
  rank: number;
  symbol: string;
  timeframe: string;
  eligible: boolean;
  winner: boolean;
  validation: {
    median_sharpe: number | null;
    median_crr: number | null;
    benchmark_crr: number | null;
  };
}

export interface MarketSelection {
  ok: boolean;
  error?: string;
  filename?: string;
  created_at?: string;
  ranking?: MarketRankingRow[];
  winner?: { symbol: string; timeframe: string };
  test?: {
    passed: number;
    required: number;
    total: number;
    accepted: boolean;
    benchmark_metrics: PaperMetrics;
  };
}

export interface Trade {
  id?: number;
  side: "long" | "short";
  units: number;
  entry_time?: string;
  exit_time?: string | null;
  entry_rate?: number | null;
  exit_rate?: number | null;
  entry?: number;
  exit?: number;
  pnl: number | null;
  pips: number | null;
  reason: string | null;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface Band {
  time: number;
  upper: number;
  mid: number;
  lower: number;
}

export interface LogLine {
  ts: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface BotSettings {
  active_strategy: string;
  timeframe: string;
  bb_period: number;
  bb_std: number;
  atr_period: number;
  sl_atr_mult: number;
  min_band_width_pips: number;
  rsi_period: number;
  rsi_overbought: number;
  rsi_oversold: number;
  wyckoff_range_period?: number;
  wyckoff_volume_mult?: number;
  wyckoff_tp_mult?: number;
  risk_per_trade: number;
  daily_loss_limit: number;
  max_trades_per_day: number;
  max_spread_pips: number;
  fixed_units: number;
}

export interface BacktestSummary {
  trades: number;
  net_profit: number;
  return_pct: number;
  win_rate_pct: number;
  profit_factor: number | null;
  max_drawdown_pct: number;
  avg_trade: number;
  total_pips: number;
}

export interface BacktestState {
  status: "idle" | "running" | "done" | "error";
  note?: string;
  error?: string;
  source?: string;
  synthetic?: boolean;
  timeframe?: string;
  candles?: number;
  period?: { from: string; to: string };
  params?: {
    active_strategy?: string;
    bb_period?: number;
    bb_std?: number;
    rsi_period?: number;
    rsi_overbought?: number;
    rsi_oversold?: number;
    wyckoff_range_period?: number;
    wyckoff_volume_mult?: number;
    wyckoff_tp_mult?: number;
    atr_period: number;
    sl_atr_mult: number;
    risk_per_trade: number;
    spread_pips: number;
    initial_equity: number;
  };
  summary?: BacktestSummary;
  equity?: { time: number; value: number }[];
  trades?: Trade[];
  started?: string;
  finished?: string;
}
