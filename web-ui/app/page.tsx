"use client";
/* Dashboard: gráfico de velas con bandas, ticker, controles y posiciones. */

import { useEffect, useMemo, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { CandleChart } from "@/components/charts";
import LogsPanel from "@/components/LogsPanel";
import PositionsPanel from "@/components/PositionsPanel";
import StrategyControls from "@/components/StrategyControls";
import { getJSON, postJSON } from "@/lib/api";
import { fmt, fmtPx, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Band, Candle, Trade } from "@/lib/types";

const TFS = ["m5", "m15", "h1", "h4"] as const;

export default function Dashboard() {
  const { status, prices, floatingPl, candleVersion, wsConnected } = useLive();
  const [tf, setTf] = useState<string>("m15");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [bands, setBands] = useState<Band[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [panelMsg, setPanelMsg] = useState("");

  const activeStrategy = status?.active_strategy || "bollinger";

  async function handleStrategyChange(strategyKey: string) {
    await postJSON("/api/settings", { active_strategy: strategyKey });
  }

  useEffect(() => {
    let alive = true;
    getJSON<{ candles: Candle[]; bands: Band[] }>(`/api/candles?count=200&tf=${tf}`)
      .then((d) => { if (alive) { setCandles(d.candles); setBands(d.bands); } })
      .catch(() => {});
    getJSON<Trade[]>("/api/trades?limit=100")
      .then((t) => alive && setTrades(t))
      .catch(() => {});
    return () => { alive = false; };
  }, [tf, candleVersion, activeStrategy]);

  const markers = useMemo<SeriesMarker<Time>[]>(() => {
    if (tf !== "m15") return [];
    return trades
      .filter((t) => t.entry_time)
      .map((t) => ({
        time: (Math.floor(new Date(t.entry_time!).getTime() / 1000 / 900) * 900) as Time,
        position: t.side === "long" ? ("belowBar" as const) : ("aboveBar" as const),
        color: t.side === "long" ? "#4ade80" : "#f0716a",
        shape: t.side === "long" ? ("arrowUp" as const) : ("arrowDown" as const),
        text: t.side === "long" ? "B" : "S",
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));
  }, [trades, tf]);

  return (
    <div className="dash-grid">
      <div className="col-main">
        <div className="card">
          <div className="chart-head">
            <div className="pair">
              <span className="pair-name">EUR/USD</span>
              <span className="pair-price">{fmtPx(prices?.bid)}</span>
              <span className={`live-tag${wsConnected ? "" : " off"}`}>
                <span className="dot-live" />
                {wsConnected ? "LIVE" : "RECONECTANDO…"}
              </span>
            </div>
            <div className="tf-group">
              {TFS.map((t) => (
                <button
                  key={t}
                  className={`tf-btn${tf === t ? " active" : ""}`}
                  onClick={() => setTf(t)}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <CandleChart candles={candles} bands={bands} markers={markers} tall />
          <div className="chart-foot">
            <span>BID <b>{fmtPx(prices?.bid)}</b></span>
            <span>ASK <b>{fmtPx(prices?.ask)}</b></span>
            <span>SPREAD <b>{fmt(prices?.spread_pips, 1)}</b> pips</span>
            <span>
              P&L FLOTANTE{" "}
              <b className={floatingPl >= 0 ? "pos" : "neg"}>{sign(floatingPl)}</b>
            </span>
          </div>
        </div>
        <StrategyControls />
      </div>
      <div className="col-side">
        <div className="card" style={{ marginBottom: "16px", padding: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px" }}>
              ESTRATEGIA ACTIVA
            </span>
            <select
              value={activeStrategy}
              onChange={(e) => handleStrategyChange(e.target.value)}
              style={{
                background: "var(--card2)",
                border: "1px solid var(--border)",
                borderRadius: "6px",
                color: "var(--text)",
                fontSize: "13px",
                fontWeight: "600",
                padding: "6px 12px",
                outline: "none",
                cursor: "pointer",
              }}
            >
              <option value="bollinger">Reversión Bollinger</option>
              <option value="rsi">Estrategia RSI</option>
              <option value="wyckoff_1">Método Wyckoff 1</option>
            </select>
          </div>
        </div>
        <PositionsPanel onAction={(m) => setPanelMsg(m)} />
        <div className="card">
          <div className="card-head">
            <div className="card-title">▤ SYSTEM LOGS</div>
            <span className="hint">{panelMsg}</span>
          </div>
          <LogsPanel />
        </div>
      </div>
    </div>
  );
}
