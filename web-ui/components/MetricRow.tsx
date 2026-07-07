"use client";

import { fmt, money, sign } from "@/lib/format";
import { useLive } from "@/lib/live";

export default function MetricRow() {
  const { status } = useLive();
  const eq = status?.account?.equity;
  const usable = status?.account?.usable_margin;
  const dayPct = status?.daily_pl_pct ?? 0;
  const dayAbs = status?.daily_pl_abs ?? 0;
  const dd = status?.max_drawdown_pct ?? 0;

  return (
    <div className="metric-row">
      <div className="metric-card">
        <div className="m-lbl">TOTAL EQUITY</div>
        <div className="m-val">{money(eq)}</div>
        <div className={`m-sub ${dayPct >= 0 ? "pos" : "neg"}`}>{sign(dayPct, "% hoy")}</div>
      </div>
      <div className="metric-card">
        <div className="m-lbl">FREE MARGIN</div>
        <div className="m-val">{money(usable)}</div>
        <div className="m-sub">{eq && usable != null ? fmt((usable / eq) * 100, 1) + "% del equity" : "—"}</div>
      </div>
      <div className="metric-card">
        <div className="m-lbl">DAILY PNL</div>
        <div className={`m-val ${dayAbs >= 0 ? "pos" : "neg"}`}>
          {dayAbs >= 0 ? "+" : "-"}${fmt(Math.abs(dayAbs))}
        </div>
        <div className="m-sub">
          Trades hoy: {status ? `${status.trades_today} / ${status.max_trades_per_day}` : "—"}
        </div>
      </div>
      <div className="metric-card">
        <div className="m-lbl">MAX DRAWDOWN</div>
        <div className={`m-val ${dd <= -5 ? "neg" : dd < 0 ? "" : "pos"}`}>{fmt(dd, 1)}%</div>
        <div className="m-sub">Target: &lt; 5%</div>
      </div>
    </div>
  );
}
