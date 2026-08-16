"use client";
/* Dashboard: gráfico de velas con bandas, ticker, controles y posiciones. */

import { useEffect, useMemo, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { CandleChart } from "@/components/charts";
import FsrppoPanel from "@/components/FsrppoPanel";
import InstrumentPicker from "@/components/InstrumentPicker";
import LogsPanel from "@/components/LogsPanel";
import PositionsPanel from "@/components/PositionsPanel";
import StrategyControls from "@/components/StrategyControls";
import { getJSON, postJSON } from "@/lib/api";
import { fmt, fmtPx, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Band, Candle, Trade } from "@/lib/types";

const TFS = ["m5", "m15", "h1", "h4", "d1"] as const;

export default function Dashboard() {
  const { status, prices, floatingPl, candleVersion, wsConnected, refreshStatus } = useLive();
  // Decimales e instrumento vienen del status: la UI ya no asume EUR/USD.
  const digits = status?.digits ?? 5;
  const symbol = status?.instrument ?? "—";
  const [tf, setTf] = useState<string>("m15");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [bands, setBands] = useState<Band[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [panelMsg, setPanelMsg] = useState("");
  const [dataError, setDataError] = useState("");
  const [strategyBusy, setStrategyBusy] = useState(false);

  const activeStrategy = status?.active_strategy || "bollinger";

  async function handleStrategyChange(strategyKey: string) {
    setStrategyBusy(true);
    setPanelMsg("");
    try {
      const result = await postJSON<{ ok: boolean; error?: string }>("/api/settings", { active_strategy: strategyKey });
      if (result.ok) await refreshStatus();
      setPanelMsg(result.ok ? "Estrategia actualizada." : `Error: ${result.error ?? "no se pudo actualizar"}`);
    } catch {
      setPanelMsg("Error: no se pudo actualizar la estrategia.");
    } finally {
      setStrategyBusy(false);
    }
  }

  useEffect(() => {
    let alive = true;
    setDataError("");
    getJSON<{ candles: Candle[]; bands: Band[] }>(`/api/candles?count=200&tf=${tf}`)
      .then((d) => { if (alive) { setCandles(d.candles); setBands(d.bands); } })
      .catch(() => alive && setDataError("No se pudo cargar el gráfico. Comprueba la conexión e inténtalo de nuevo."));
    getJSON<Trade[]>("/api/trades?limit=100")
      .then((t) => alive && setTrades(t))
      .catch(() => alive && setDataError("No se pudieron cargar todos los datos de operación."));
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
              <span className="pair-name">{symbol}</span>
              <span className="pair-price">{fmtPx(prices?.bid, digits)}</span>
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
                  type="button"
                  aria-pressed={tf === t}
                  aria-label={`Mostrar velas de ${t.toUpperCase()}`}
                  onClick={() => setTf(t)}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          {status?.market_open === false && !status?.connected && (
            <div className="inline-alert" style={{ background: "rgba(59, 130, 246, 0.12)", borderColor: "rgba(59, 130, 246, 0.3)", color: "#93c5fd", marginBottom: "12px" }} role="status">
              <strong>Mercado cerrado:</strong> {status.market_status} El bot reanudará la conexión automáticamente al abrir el mercado.
            </div>
          )}
          {dataError && <div className="inline-alert" role="alert">{dataError}</div>}
          <CandleChart candles={candles} bands={bands} markers={markers} digits={digits} label={`Gráfico de velas de ${symbol} en ${tf.toUpperCase()}`} tall />
          <div className="chart-foot">
            <span>BID <b>{fmtPx(prices?.bid, digits)}</b></span>
            <span>ASK <b>{fmtPx(prices?.ask, digits)}</b></span>
            <span>SPREAD <b>{fmt(prices?.spread_pips, 1)}</b> pips</span>
            <span>
              P&L FLOTANTE{" "}
              <b className={floatingPl >= 0 ? "pos" : "neg"}>{sign(floatingPl)}</b>
            </span>
          </div>
        </div>
        <StrategyControls />
        <FsrppoPanel />
      </div>
      <div className="col-side">
        <InstrumentPicker onAction={(m) => setPanelMsg(m)} />
        <div className="card" style={{ marginBottom: "16px", padding: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label className="field-label" htmlFor="active-strategy">ESTRATEGIA ACTIVA</label>
            <select
              id="active-strategy"
              value={activeStrategy}
              disabled={strategyBusy}
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
              {/* FSRPPO gestiona posición neta y necesita un modelo activo
                  entrenado para el instrumento seleccionado. */}
              <option value="fsrppo">FSRPPO (posición neta)</option>
              <option value="bollinger">Reversión Bollinger</option>
              <option value="rsi">Estrategia RSI</option>
              <option value="wyckoff_1">Método Wyckoff 1</option>
            </select>
          </div>
        </div>
        <PositionsPanel onAction={(m) => setPanelMsg(m)} />
        <div className="card">
          <div className="card-head">
            <div className="card-title">REGISTRO DEL SISTEMA</div>
            <span className="hint" role="status" aria-live="polite">{panelMsg}</span>
          </div>
          <LogsPanel />
        </div>
      </div>
    </div>
  );
}
