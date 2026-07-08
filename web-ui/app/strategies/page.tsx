"use client";
/* Estrategias de Trading (Configuración y Backtesting integrados por estrategia) */

import { useEffect, useState, useCallback, useRef } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { AreaChart } from "@/components/charts";
import { fmt, fmtPx, isoShort, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { BotSettings, BacktestState } from "@/lib/types";

const TF_OPTIONS = [
  { value: "m5", label: "M5 — 5 minutos" },
  { value: "m15", label: "M15 — 15 minutos (el del bot)" },
  { value: "m30", label: "M30 — 30 minutos" },
  { value: "h1", label: "H1 — 1 hora" },
  { value: "h4", label: "H4 — 4 horas" },
  { value: "d1", label: "D1 — diario" },
];

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

interface BacktestInputs {
  source: string;
  timeframe: string;
  dateFrom: string;
  dateTo: string;
  equity: number;
  spread: number;
  file: File | null;
}

export default function StrategiesPage() {
  const { status, backtestVersion } = useLive();
  const activeStrategy = status?.active_strategy || "bollinger";
  const simulated = status?.mode === "simulado";

  const [values, setValues] = useState<Record<string, any>>({});
  const [expanded, setExpanded] = useState<string | null>("bollinger");
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  // Estados independientes de Backtesting por estrategia
  const [btSettings, setBtSettings] = useState<Record<string, BacktestInputs>>({
    bollinger: { source: "synthetic", timeframe: "m15", dateFrom: isoDay(new Date(Date.now() - 730 * 86400_000)), dateTo: isoDay(new Date()), equity: 10000, spread: 1.2, file: null },
    rsi: { source: "synthetic", timeframe: "m15", dateFrom: isoDay(new Date(Date.now() - 730 * 86400_000)), dateTo: isoDay(new Date()), equity: 10000, spread: 1.2, file: null },
    wyckoff_1: { source: "synthetic", timeframe: "m15", dateFrom: isoDay(new Date(Date.now() - 730 * 86400_000)), dateTo: isoDay(new Date()), equity: 10000, spread: 1.2, file: null },
  });
  const [btResults, setBtResults] = useState<Record<string, BacktestState>>({});
  const [btMsgs, setBtMsgs] = useState<Record<string, { text: string; cls: string } | null>>({});
  const [runningStrategy, setRunningStrategy] = useState<string | null>(null);
  const [showTrades, setShowTrades] = useState<Record<string, boolean>>({});

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Carga de ajustes y último backtest en mount
  useEffect(() => {
    getJSON<BotSettings>("/api/settings").then((s) => {
      setValues({
        timeframe: s.timeframe || "m15",
        bb_period: s.bb_period,
        bb_std: s.bb_std,
        atr_period: s.atr_period,
        sl_atr_mult: s.sl_atr_mult,
        min_band_width_pips: s.min_band_width_pips,
        rsi_period: s.rsi_period ?? 14,
        rsi_overbought: s.rsi_overbought ?? 70,
        rsi_oversold: s.rsi_oversold ?? 30,
        wyckoff_range_period: s.wyckoff_range_period ?? 20,
        wyckoff_volume_mult: s.wyckoff_volume_mult ?? 1.5,
        wyckoff_tp_mult: s.wyckoff_tp_mult ?? 2.0,
      });
      if (s.active_strategy) {
        setExpanded(s.active_strategy);
      }
    }).catch(() => {});

    // Recuperar la última simulación realizada
    getJSON<BacktestState>("/api/backtest").then((s) => {
      if (s && s.status === "done" && s.params?.active_strategy) {
        setBtResults({ [s.params.active_strategy]: s });
      }
    }).catch(() => {});
  }, []);

  // Guardar cambios de parámetros (sin activar la estrategia)
  async function save(strategyKey: string) {
    const payload: Record<string, any> = {
      timeframe: values.timeframe || "m15",
      atr_period: values.atr_period,
      sl_atr_mult: values.sl_atr_mult,
    };
    if (strategyKey === "bollinger") {
      payload.bb_period = values.bb_period;
      payload.bb_std = values.bb_std;
      payload.min_band_width_pips = values.min_band_width_pips;
    } else if (strategyKey === "rsi") {
      payload.rsi_period = values.rsi_period;
      payload.rsi_overbought = values.rsi_overbought;
      payload.rsi_oversold = values.rsi_oversold;
    } else if (strategyKey === "wyckoff_1") {
      payload.wyckoff_range_period = values.wyckoff_range_period;
      payload.wyckoff_volume_mult = values.wyckoff_volume_mult;
      payload.wyckoff_tp_mult = values.wyckoff_tp_mult;
    }

    const r = await postJSON<{ ok: boolean; settings: BotSettings }>("/api/settings", payload);
    if (r.ok) {
      setValues({
        timeframe: r.settings.timeframe || "m15",
        bb_period: r.settings.bb_period,
        bb_std: r.settings.bb_std,
        atr_period: r.settings.atr_period,
        sl_atr_mult: r.settings.sl_atr_mult,
        min_band_width_pips: r.settings.min_band_width_pips,
        rsi_period: r.settings.rsi_period,
        rsi_overbought: r.settings.rsi_overbought,
        rsi_oversold: r.settings.rsi_oversold,
        wyckoff_range_period: r.settings.wyckoff_range_period,
        wyckoff_volume_mult: r.settings.wyckoff_volume_mult,
        wyckoff_tp_mult: r.settings.wyckoff_tp_mult,
      });
      setMsg({ text: `✓ Parámetros guardados correctamente.`, ok: true });
    } else {
      setMsg({ text: "Error al guardar", ok: false });
    }
    setTimeout(() => setMsg(null), 5000);
  }

  const toggleExpand = (key: string) => {
    setExpanded(expanded === key ? null : key);
  };

  // Polling de Backtesting
  const refresh = useCallback(async () => {
    try {
      const s = await getJSON<BacktestState>("/api/backtest");
      
      if (s.status === "running") {
        if (runningStrategy) {
          setBtMsgs(prev => ({
            ...prev,
            [runningStrategy]: { text: s.note || "Ejecutando…", cls: "" }
          }));
        }
        if (!pollRef.current) pollRef.current = setInterval(refresh, 2000);
      } else {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }

        const stratKey = s.params?.active_strategy || runningStrategy;
        if (stratKey) {
          setBtResults(prev => ({ ...prev, [stratKey]: s }));
          if (s.status === "error") {
            setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Error: " + s.error, cls: "err" } }));
          } else if (s.status === "done") {
            setBtMsgs(prev => ({
              ...prev,
              [stratKey]: {
                text: `Terminado ${isoShort(s.finished)} UTC — ${s.candles} velas (${s.source})`,
                cls: "ok",
              }
            }));
          }
          if (runningStrategy === stratKey) {
            setRunningStrategy(null);
          }
        }
      }
    } catch {
      /* backend caído */
    }
  }, [runningStrategy]);

  useEffect(() => {
    refresh();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [refresh, backtestVersion]);

  // Asegura que en simulado se use sintético
  useEffect(() => {
    Object.keys(btSettings).forEach((key) => {
      if (simulated && btSettings[key].source === "fxcm") {
        setBtSettings(prev => ({
          ...prev,
          [key]: { ...prev[key], source: "synthetic" }
        }));
      }
    });
  }, [simulated]);

  // Lanzar Backtest
  async function runBacktestFor(stratKey: string) {
    const s = btSettings[stratKey];
    if (!s) return;
    setRunningStrategy(stratKey);
    setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Preparando datos…", cls: "" } }));

    try {
      if (s.source === "csv" && s.file) {
        setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Subiendo CSV…", cls: "" } }));
        const fd = new FormData();
        fd.append("file", s.file);
        const up = await (await fetch("/api/backtest/csv", { method: "POST", body: fd })).json();
        if (!up.ok) {
          setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Error subiendo CSV: " + up.error, cls: "err" } }));
          setRunningStrategy(null);
          return;
        }
      }

      const tf = values.timeframe || "m15";

      const r = await postJSON("/api/backtest", {
        source: s.source,
        timeframe: tf,
        date_from: s.dateFrom,
        date_to: s.dateTo,
        equity: s.equity,
        spread_pips: s.spread,
        strategy: stratKey,
        strategy_params: values,
      });

      if (!r.ok) {
        setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Error: " + r.error, cls: "err" } }));
        setRunningStrategy(null);
        return;
      }
    } catch (e: any) {
      setBtMsgs(prev => ({ ...prev, [stratKey]: { text: "Error: " + e.message, cls: "err" } }));
      setRunningStrategy(null);
    }
  }

  // Renderizador de formulario de backtest
  function renderBacktestForm(stratKey: string) {
    const s = btSettings[stratKey];
    if (!s) return null;
    const setSetting = (key: string, val: any) => {
      setBtSettings(prev => ({
        ...prev,
        [stratKey]: { ...prev[stratKey], [key]: val }
      }));
    };
    const isBtRunning = runningStrategy === stratKey;

    const selectStyle = {
      background: "var(--card2)",
      border: "1px solid var(--border)",
      borderRadius: "8px",
      color: "var(--text)",
      fontSize: "14px",
      fontWeight: "600",
      padding: "11px 12px",
      outline: "none",
      marginTop: "7px",
      width: "100%"
    };

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginTop: "16px", borderTop: "1px solid var(--border)", paddingTop: "16px" }}>
        <h4 style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px" }}>
          ≋ AJUSTES DE SIMULACIÓN (BACKTESTING)
        </h4>
        <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <label style={{ gridColumn: "span 2" }}>
            FUENTE DE DATOS
            <select 
              value={s.source} 
              onChange={(e) => setSetting("source", e.target.value)}
              style={selectStyle}
            >
              <option value="fxcm" disabled={simulated}>FXCM histórico (real)</option>
              <option value="synthetic">Sintético (prueba)</option>
              <option value="csv">CSV subido</option>
            </select>
          </label>
          <label>
            DESDE
            <input type="date" value={s.dateFrom} max={s.dateTo} onChange={(e) => setSetting("dateFrom", e.target.value)} />
          </label>
          <label>
            HASTA
            <input type="date" value={s.dateTo} min={s.dateFrom} max={isoDay(new Date())} onChange={(e) => setSetting("dateTo", e.target.value)} />
          </label>
          <label>
            EQUITY INICIAL ($)
            <input type="number" min={100} step={100} value={s.equity} onChange={(e) => setSetting("equity", +e.target.value)} />
          </label>
          <label>
            SPREAD (PIPS)
            <input type="number" min={0} max={10} step={0.1} value={s.spread} onChange={(e) => setSetting("spread", +e.target.value)} />
          </label>
          {s.source === "csv" && (
            <label style={{ gridColumn: "span 2" }}>
              CSV FILE
              <input
                type="file"
                accept=".csv"
                onChange={(e) => setSetting("file", e.target.files?.[0] ?? null)}
              />
            </label>
          )}
        </div>
        <button
          className="btn btn-start bt-run"
          disabled={runningStrategy !== null}
          onClick={() => runBacktestFor(stratKey)}
          style={{ marginTop: "8px", width: "100%" }}
        >
          {isBtRunning ? "EJECUTANDO SIMULACIÓN…" : "EJECUTAR BACKTEST"}
        </button>
        {btMsgs[stratKey] && (
          <div className={`manual-msg ${btMsgs[stratKey]?.cls ?? ""}`} style={{ marginTop: "8px" }}>
            {btMsgs[stratKey]?.text}
          </div>
        )}
      </div>
    );
  }

  // Renderizador de resultados de backtest
  function renderBacktestResults(stratKey: string) {
    const st = btResults[stratKey];
    const s = st?.summary;
    const isBtRunning = runningStrategy === stratKey;

    if (isBtRunning) {
      return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", justifyContent: "center", alignItems: "center", minHeight: "250px" }}>
          <div className="spinner" style={{ marginBottom: "16px" }}></div>
          <span style={{ fontSize: "13px", fontWeight: "600", color: "var(--text-muted)" }}>
            Simulando estrategia...
          </span>
        </div>
      );
    }

    if (!st || !s) {
      return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", justifyContent: "center", alignItems: "center", minHeight: "250px", border: "1px dashed var(--border)", borderRadius: "8px", padding: "24px", textAlign: "center" }}>
          <span style={{ fontSize: "32px", marginBottom: "8px" }}>≋</span>
          <span style={{ fontSize: "13px", fontWeight: "600", color: "var(--text)" }}>
            Sin Simulación Reciente
          </span>
          <span style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "6px", maxWidth: "250px" }}>
            Configure los parámetros a la izquierda y presione "Ejecutar Backtest" para ver el rendimiento histórico de esta estrategia.
          </span>
        </div>
      );
    }

    const pfInf = s.profit_factor == null && s.trades > 0 && s.net_profit > 0;
    const pfText = pfInf ? "∞" : s.profit_factor == null ? "—" : fmt(s.profit_factor);

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <h4 style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px" }}>
          📊 RENDIMIENTO DE LA SIMULACIÓN
        </h4>

        {st.synthetic ? (
          <div className="bt-banner warn" style={{ padding: "8px 12px", fontSize: "11px", borderRadius: "6px", margin: 0 }}>
            ⚠ DATOS SINTÉTICOS — solo para pruebas del pipeline.
          </div>
        ) : s.trades === 0 ? (
          <div className="bt-banner warn" style={{ padding: "8px 12px", fontSize: "11px", borderRadius: "6px", margin: 0 }}>
            Sin operaciones en el período probado.
          </div>
        ) : pfInf || (s.profit_factor ?? 0) >= 1 ? (
          <div className="bt-banner good" style={{ padding: "8px 12px", fontSize: "11px", borderRadius: "6px", margin: 0 }}>
            ✓ EXPECTATIVA POSITIVA (PF {pfText}).
          </div>
        ) : (
          <div className="bt-banner bad" style={{ padding: "8px 12px", fontSize: "11px", borderRadius: "6px", margin: 0 }}>
            ✗ EXPECTATIVA NEGATIVA (PF {pfText}).
          </div>
        )}

        <div className="metric-row inner" style={{ gap: "8px", margin: 0, padding: 0 }}>
          <Metric label="NET PROFIT" val={sign(s.net_profit)} tone={s.net_profit} />
          <Metric label="RETORNO" val={sign(s.return_pct, "%")} tone={s.return_pct} />
          <Metric label="WIN RATE" val={fmt(s.win_rate_pct, 1) + "%"} />
          <Metric label="PROFIT FACTOR" val={pfText} tone={pfInf ? 1 : s.profit_factor == null ? undefined : s.profit_factor - 1} />
        </div>
        <div className="metric-row inner" style={{ gap: "8px", margin: 0, padding: 0 }}>
          <Metric label="MAX DD" val={fmt(s.max_drawdown_pct, 1) + "%"} tone={s.max_drawdown_pct + 5} />
          <Metric label="TRADES" val={String(s.trades)} />
          <Metric label="PIPS NETOS" val={fmt(s.total_pips, 1)} tone={s.total_pips} />
          <Metric label="AVG TRADE" val={sign(s.avg_trade)} tone={s.avg_trade} />
        </div>

        <div className="card mb" style={{ padding: "12px", minHeight: "190px", marginBottom: 0 }}>
          <div className="card-head" style={{ paddingBottom: "4px", marginBottom: "4px" }}>
            <div className="card-title" style={{ fontSize: "10px" }}>∿ CURVA DE BALANCE (EQUITY)</div>
          </div>
          <div style={{ height: "140px", width: "100%" }}>
            <AreaChart data={st.equity ?? []} color="#4ade80" fit />
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            className="link-btn"
            onClick={() => setShowTrades(prev => ({ ...prev, [stratKey]: !prev[stratKey] }))}
            style={{ fontSize: "12px", color: "var(--primary)", fontWeight: "600", padding: 0 }}
          >
            {showTrades[stratKey] ? "▲ Ocultar Trades de la Simulación" : "▼ Mostrar Trades de la Simulación"}
          </button>
        </div>
      </div>
    );
  }

  // Renderizador de listado de transacciones
  function renderBacktestTradesTable(stratKey: string) {
    const st = btResults[stratKey];
    if (!st || !showTrades[stratKey] || runningStrategy === stratKey) return null;

    return (
      <div className="card" style={{ marginTop: "16px", padding: "16px" }}>
        <div className="card-head" style={{ paddingBottom: "12px" }}>
          <div className="card-title">⟲ TRADES DEL BACKTEST (ÚLTIMOS 500)</div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>DIR</th><th>UNIDADES</th><th>ENTRADA</th><th>SALIDA</th>
                <th>PIPS</th><th>P&L</th><th>MOTIVO</th><th>FECHA</th>
              </tr>
            </thead>
            <tbody>
              {(st.trades ?? []).slice().reverse().map((t, i) => (
                <tr key={i}>
                  <td className={t.side === "long" ? "dir-long" : "dir-short"}>
                    {t.side === "long" ? "▲ BUY" : "▼ SELL"}
                  </td>
                  <td>{fmt(t.units, 0)}</td>
                  <td>{fmtPx(t.entry)}</td>
                  <td>{fmtPx(t.exit)}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{fmt(t.pips, 1)}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{sign(t.pnl)}</td>
                  <td>{(t.reason ?? "—").toUpperCase()}</td>
                  <td>{isoShort(t.exit_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  const selectTimeframe = (
    <label>
      TEMPORALIDAD (TIMEFRAME)
      <select
        value={values.timeframe ?? "m15"}
        onChange={(e) => setValues({ ...values, timeframe: e.target.value })}
        style={{
          background: "var(--card2)",
          border: "1px solid var(--border)",
          borderRadius: "8px",
          color: "var(--text)",
          fontSize: "14px",
          fontWeight: "600",
          padding: "11px 12px",
          outline: "none",
          marginTop: "7px"
        }}
      >
        <option value="m5">M5 — 5 minutos</option>
        <option value="m15">M15 — 15 minutos</option>
        <option value="m30">M30 — 30 minutos</option>
        <option value="h1">H1 — 1 hora</option>
        <option value="h4">H4 — 4 horas</option>
      </select>
    </label>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      
      {/* SECCIÓN CONFIGURACIÓN */}
      <div>
        <h2 style={{ fontSize: "14px", fontWeight: "bold", marginBottom: "16px", color: "var(--text-muted)", letterSpacing: "1px" }}>
          ⚙ ESTRATEGIAS DE TRADING Y SIMULACIÓN
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          
          {/* BOLLINGER STRATEGY CARD */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div 
              className="accordion-header" 
              onClick={() => toggleExpand("bollinger")}
              style={{ background: "var(--card)", padding: "20px 24px" }}
            >
              <div className="strategy-title-row">
                <span className="strategy-name" style={{ fontSize: "16px" }}>Reversión a la Media (Bandas de Bollinger)</span>
                {activeStrategy === "bollinger" && <span className="chip ok ml">ACTIVA</span>}
              </div>
              <span className="arrow" style={{ fontSize: "14px" }}>{expanded === "bollinger" ? "▲" : "▼"}</span>
            </div>
            
            {expanded === "bollinger" && (
              <div className="accordion-content" style={{ padding: "24px", background: "var(--card)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "24px" }}>
                  {/* Izquierda: Ajustes */}
                  <div>
                    <h4 style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px", marginBottom: "12px" }}>
                      ⚙ AJUSTES DE LA ESTRATEGIA
                    </h4>
                    <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                      {selectTimeframe}
                      <label>
                        PERÍODO BOLLINGER
                        <input
                          type="number"
                          min={10}
                          max={50}
                          value={values.bb_period ?? ""}
                          onChange={(e) => setValues({ ...values, bb_period: +e.target.value })}
                        />
                      </label>
                      <label>
                        DESVIACIÓN STD
                        <input
                          type="number"
                          min={1}
                          max={3}
                          step={0.1}
                          value={values.bb_std ?? ""}
                          onChange={(e) => setValues({ ...values, bb_std: +e.target.value })}
                        />
                      </label>
                      <label>
                        PERÍODO ATR
                        <input
                          type="number"
                          min={5}
                          max={50}
                          value={values.atr_period ?? ""}
                          onChange={(e) => setValues({ ...values, atr_period: +e.target.value })}
                        />
                      </label>
                      <label>
                        MULT. STOP (×ATR)
                        <input
                          type="number"
                          min={0.5}
                          max={5}
                          step={0.1}
                          value={values.sl_atr_mult ?? ""}
                          onChange={(e) => setValues({ ...values, sl_atr_mult: +e.target.value })}
                        />
                      </label>
                      <label>
                        ANCHO MÍN. BANDAS (PIPS)
                        <input
                          type="number"
                          min={0}
                          max={50}
                          value={values.min_band_width_pips ?? ""}
                          onChange={(e) => setValues({ ...values, min_band_width_pips: +e.target.value })}
                        />
                      </label>
                    </div>
                    {renderBacktestForm("bollinger")}
                    <button className="btn btn-start" onClick={() => save("bollinger")} style={{ marginTop: "16px", width: "100%", background: "var(--border)", color: "var(--text)", border: "1px solid var(--border)" }}>
                      GUARDAR AJUSTES
                    </button>
                  </div>

                  {/* Derecha: Resultados del backtest */}
                  <div>
                    {renderBacktestResults("bollinger")}
                  </div>
                </div>
                {renderBacktestTradesTable("bollinger")}
              </div>
            )}
          </div>

          {/* RSI STRATEGY CARD */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div 
              className="accordion-header" 
              onClick={() => toggleExpand("rsi")}
              style={{ background: "var(--card)", padding: "20px 24px" }}
            >
              <div className="strategy-title-row">
                <span className="strategy-name" style={{ fontSize: "16px" }}>Estrategia RSI (Relative Strength Index)</span>
                {activeStrategy === "rsi" && <span className="chip ok ml">ACTIVA</span>}
              </div>
              <span className="arrow" style={{ fontSize: "14px" }}>{expanded === "rsi" ? "▲" : "▼"}</span>
            </div>
            
            {expanded === "rsi" && (
              <div className="accordion-content" style={{ padding: "24px", background: "var(--card)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "24px" }}>
                  {/* Izquierda: Ajustes */}
                  <div>
                    <h4 style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px", marginBottom: "12px" }}>
                      ⚙ AJUSTES DE LA ESTRATEGIA
                    </h4>
                    <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                      {selectTimeframe}
                      <label>
                        PERÍODO RSI
                        <input
                          type="number"
                          min={5}
                          max={50}
                          value={values.rsi_period ?? ""}
                          onChange={(e) => setValues({ ...values, rsi_period: +e.target.value })}
                        />
                      </label>
                      <label>
                        LÍMITE SOBRECOMPRA
                        <input
                          type="number"
                          min={50}
                          max={90}
                          value={values.rsi_overbought ?? ""}
                          onChange={(e) => setValues({ ...values, rsi_overbought: +e.target.value })}
                        />
                      </label>
                      <label>
                        LÍMITE SOBREVENTA
                        <input
                          type="number"
                          min={10}
                          max={50}
                          value={values.rsi_oversold ?? ""}
                          onChange={(e) => setValues({ ...values, rsi_oversold: +e.target.value })}
                        />
                      </label>
                      <label>
                        PERÍODO ATR
                        <input
                          type="number"
                          min={5}
                          max={50}
                          value={values.atr_period ?? ""}
                          onChange={(e) => setValues({ ...values, atr_period: +e.target.value })}
                        />
                      </label>
                      <label>
                        MULT. STOP (×ATR)
                        <input
                          type="number"
                          min={0.5}
                          max={5}
                          step={0.1}
                          value={values.sl_atr_mult ?? ""}
                          onChange={(e) => setValues({ ...values, sl_atr_mult: +e.target.value })}
                        />
                      </label>
                    </div>
                    {renderBacktestForm("rsi")}
                    <button className="btn btn-start" onClick={() => save("rsi")} style={{ marginTop: "16px", width: "100%", background: "var(--border)", color: "var(--text)", border: "1px solid var(--border)" }}>
                      GUARDAR AJUSTES
                    </button>
                  </div>

                  {/* Derecha: Resultados del backtest */}
                  <div>
                    {renderBacktestResults("rsi")}
                  </div>
                </div>
                {renderBacktestTradesTable("rsi")}
              </div>
            )}
          </div>

          {/* WYCKOFF STRATEGY CARD */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div 
              className="accordion-header" 
              onClick={() => toggleExpand("wyckoff_1")}
              style={{ background: "var(--card)", padding: "20px 24px" }}
            >
              <div className="strategy-title-row">
                <span className="strategy-name" style={{ fontSize: "16px" }}>Método Wyckoff 1 (Ruptura de Rango con Volumen)</span>
                {activeStrategy === "wyckoff_1" && <span className="chip ok ml">ACTIVA</span>}
              </div>
              <span className="arrow" style={{ fontSize: "14px" }}>{expanded === "wyckoff_1" ? "▲" : "▼"}</span>
            </div>
            
            {expanded === "wyckoff_1" && (
              <div className="accordion-content" style={{ padding: "24px", background: "var(--card)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "24px" }}>
                  {/* Izquierda: Ajustes */}
                  <div>
                    <h4 style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px", marginBottom: "12px" }}>
                      ⚙ AJUSTES DE LA ESTRATEGIA
                    </h4>
                    <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                      {selectTimeframe}
                      <label>
                        PERÍODO RANGO
                        <input
                          type="number"
                          min={5}
                          max={100}
                          value={values.wyckoff_range_period ?? ""}
                          onChange={(e) => setValues({ ...values, wyckoff_range_period: +e.target.value })}
                        />
                      </label>
                      <label>
                        CONFIRMACIÓN VOLUMEN (MULT)
                        <input
                          type="number"
                          min={1.0}
                          max={5.0}
                          step={0.1}
                          value={values.wyckoff_volume_mult ?? ""}
                          onChange={(e) => setValues({ ...values, wyckoff_volume_mult: +e.target.value })}
                        />
                      </label>
                      <label>
                        MULT. PROVECHO (×RISK TO TP)
                        <input
                          type="number"
                          min={0.5}
                          max={10}
                          step={0.1}
                          value={values.wyckoff_tp_mult ?? ""}
                          onChange={(e) => setValues({ ...values, wyckoff_tp_mult: +e.target.value })}
                        />
                      </label>
                    </div>
                    {renderBacktestForm("wyckoff_1")}
                    <button className="btn btn-start" onClick={() => save("wyckoff_1")} style={{ marginTop: "16px", width: "100%", background: "var(--border)", color: "var(--text)", border: "1px solid var(--border)" }}>
                      GUARDAR AJUSTES
                    </button>
                  </div>

                  {/* Derecha: Resultados del backtest */}
                  <div>
                    {renderBacktestResults("wyckoff_1")}
                  </div>
                </div>
                {renderBacktestTradesTable("wyckoff_1")}
              </div>
            )}
          </div>

        </div>

        {msg && (
          <div style={{ marginTop: 16, textAlign: "center" }}>
            <span className={`hint${msg.ok ? " ok" : " err"}`}>{msg.text}</span>
          </div>
        )}
      </div>

    </div>
  );
}

function Metric({ label, val, tone }: { label: string; val: string; tone?: number }) {
  return (
    <div className="metric-card" style={{ flex: 1, minWidth: "80px", padding: "8px" }}>
      <div className="m-lbl" style={{ fontSize: "9px" }}>{label}</div>
      <div className={`m-val${tone == null ? "" : tone >= 0 ? " pos" : " neg"}`} style={{ fontSize: "14px" }}>{val}</div>
    </div>
  );
}
