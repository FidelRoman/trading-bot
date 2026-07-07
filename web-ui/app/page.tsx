"use client";
/* Dashboard: gráfico de velas con bandas, ticker, controles y posiciones. */

import { useEffect, useMemo, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { CandleChart } from "@/components/charts";
import LogsPanel from "@/components/LogsPanel";
import PositionsPanel from "@/components/PositionsPanel";
import StrategyControls from "@/components/StrategyControls";
import { getJSON } from "@/lib/api";
import { fmt, fmtPx, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Band, Candle, Trade } from "@/lib/types";

const TFS = ["m5", "m15", "h1", "h4"] as const;

export default function Dashboard() {
  const { prices, floatingPl, candleVersion, wsConnected } = useLive();
  const [tf, setTf] = useState<string>("m15");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [bands, setBands] = useState<Band[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [panelMsg, setPanelMsg] = useState("");

  useEffect(() => {
    let alive = true;
    getJSON<{ candles: Candle[]; bands: Band[] }>(`/api/candles?count=200&tf=${tf}`)
      .then((d) => { if (alive) { setCandles(d.candles); setBands(d.bands); } })
      .catch(() => {});
    getJSON<Trade[]>("/api/trades?limit=100")
      .then((t) => alive && setTrades(t))
      .catch(() => {});
    return () => { alive = false; };
  }, [tf, candleVersion]);

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
