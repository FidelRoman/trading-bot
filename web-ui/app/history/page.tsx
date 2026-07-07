"use client";
/* Historial de operaciones cerradas + estadísticas acumuladas. */

import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";
import { fmt, fmtPx, isoShort, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Trade } from "@/lib/types";

export default function History() {
  const { status, candleVersion } = useLive();
  const [trades, setTrades] = useState<Trade[]>([]);
  const stats = status?.stats;

  useEffect(() => {
    getJSON<Trade[]>("/api/trades?limit=200").then(setTrades).catch(() => {});
  }, [candleVersion]);

  return (
    <>
      <div className="metric-row inner">
        <div className="metric-card"><div className="m-lbl">TRADES</div><div className="m-val">{stats?.trades ?? "—"}</div></div>
        <div className="metric-card"><div className="m-lbl">WIN RATE</div><div className="m-val">{fmt(stats?.win_rate_pct, 1)}%</div></div>
        <div className="metric-card"><div className="m-lbl">PROFIT FACTOR</div><div className="m-val">{stats?.profit_factor == null ? "—" : fmt(stats.profit_factor)}</div></div>
        <div className="metric-card"><div className="m-lbl">PIPS NETOS</div><div className="m-val">{fmt(stats?.total_pips, 1)}</div></div>
      </div>
      <div className="card">
        <div className="card-head"><div className="card-title">⟲ TRADE HISTORY</div></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>DIR</th><th>UNIDADES</th><th>ENTRADA</th><th>SALIDA</th>
                <th>PIPS</th><th>P&L</th><th>MOTIVO</th><th>FECHA</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={t.id ?? i}>
                  <td className={t.side === "long" ? "dir-long" : "dir-short"}>
                    {t.side === "long" ? "▲ BUY" : "▼ SELL"}
                  </td>
                  <td>{fmt(t.units, 0)}</td>
                  <td>{fmtPx(t.entry_rate)}</td>
                  <td>{fmtPx(t.exit_rate)}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{t.pips == null ? "—" : fmt(t.pips, 1)}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{t.pnl == null ? "—" : sign(t.pnl)}</td>
                  <td>{(t.reason ?? "—").toUpperCase()}</td>
                  <td>{isoShort(t.exit_time ?? t.entry_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length === 0 && <div className="empty">Sin operaciones todavía</div>}
        </div>
      </div>
    </>
  );
}
