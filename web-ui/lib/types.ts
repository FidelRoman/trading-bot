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
  bb_period: number;
  bb_std: number;
  atr_period: number;
  sl_atr_mult: number;
  min_band_width_pips: number;
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
    bb_period: number;
    bb_std: number;
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
