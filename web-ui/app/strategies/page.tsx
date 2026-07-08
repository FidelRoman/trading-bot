"use client";
/* Estrategias de Trading (Configuración y Backtesting unificados) */

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

export default function StrategiesPage() {
  const { status, backtestVersion } = useLive();
  const activeStrategy = status?.active_strategy || "bollinger";
  const simulated = status?.mode === "simulado";

  const [values, setValues] = useState<Record<string, any>>({});
  const [expanded, setExpanded] = useState<string | null>("bollinger");
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  // Estados de Backtesting
  const [strategy, setStrategy] = useState("bollinger");
  const [source, setSource] = useState("synthetic");
  const [timeframe, setTimeframe] = useState("m15");
  const [dateFrom, setDateFrom] = useState(() =>
    isoDay(new Date(Date.now() - 730 * 86400_000))
  );
  const [dateTo, setDateTo] = useState(() => isoDay(new Date()));
  const [equity, setEquity] = useState(10000);
  const [spread, setSpread] = useState(1.2);
  const [file, setFile] = useState<File | null>(null);
  const [btMsg, setBtMsg] = useState<{ text: string; cls: string } | null>(null);
  const [st, setSt] = useState<BacktestState>({ status: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
  }, []);

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

  // Lógica Backtesting
  const refresh = useCallback(async () => {
    try {
      const s = await getJSON<BacktestState>("/api/backtest");
      setSt(s);
      if (s.status === "running") {
        setBtMsg({ text: s.note || "Ejecutando…", cls: "" });
        if (!pollRef.current) pollRef.current = setInterval(refresh, 2000);
      } else {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        if (s.status === "error") setBtMsg({ text: "Error: " + s.error, cls: "err" });
        else if (s.status === "done")
          setBtMsg({
            text: `Terminado ${isoShort(s.finished)} UTC — ${s.candles} velas (${s.source})`,
            cls: "ok",
          });
      }
    } catch {
      /* backend caído */
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [refresh, backtestVersion]);

  useEffect(() => {
    if (simulated && source === "fxcm") setSource("synthetic");
  }, [simulated, source]);

  async function run() {
    if (source === "csv" && file) {
      setBtMsg({ text: "Subiendo CSV…", cls: "" });
      const fd = new FormData();
      fd.append("file", file);
      const up = await (await fetch("/api/backtest/csv", { method: "POST", body: fd })).json();
      if (!up.ok) { setBtMsg({ text: "Error subiendo CSV: " + up.error, cls: "err" }); return; }
    }
    const r = await postJSON("/api/backtest", {
      source,
      timeframe,
      date_from: dateFrom,
      date_to: dateTo,
      equity,
      spread_pips: spread,
      strategy,
    });
    if (!r.ok) { setBtMsg({ text: "Error: " + r.error, cls: "err" }); return; }
    setSt({ status: "running" });
    setBtMsg({ text: "Preparando datos…", cls: "" });
    if (!pollRef.current) pollRef.current = setInterval(refresh, 2000);
  }

  const running = st.status === "running";
  const done = st.status === "done" && st.summary;
  const s = st.summary;
  const pfInf = !!s && s.profit_factor == null && s.trades > 0 && s.net_profit > 0;
  const pfText = pfInf ? "∞" : s?.profit_factor == null ? "—" : fmt(s.profit_factor);

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
          ⚙ CONFIGURACIÓN DE ESTRATEGIAS
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          
          {/* BOLLINGER STRATEGY CARD */}
          <div className="card narrow" style={{ padding: 0, overflow: "hidden" }}>
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
                <div className="form-grid">
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
                <div className="form-actions">
                  <button className="btn btn-start" onClick={() => save("bollinger")}>
                    GUARDAR CAMBIOS
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* RSI STRATEGY CARD */}
          <div className="card narrow" style={{ padding: 0, overflow: "hidden" }}>
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
                <div className="form-grid">
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
                <div className="form-actions">
                  <button className="btn btn-start" onClick={() => save("rsi")}>
                    GUARDAR CAMBIOS
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* WYCKOFF STRATEGY CARD */}
          <div className="card narrow" style={{ padding: 0, overflow: "hidden" }}>
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
                <div className="form-grid">
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
                <div className="form-actions">
                  <button className="btn btn-start" onClick={() => save("wyckoff_1")}>
                    GUARDAR CAMBIOS
                  </button>
                </div>
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

      {/* SECCIÓN BACKTESTING */}
      <div>
        <h2 style={{ fontSize: "14px", fontWeight: "bold", marginBottom: "16px", color: "var(--text-muted)", letterSpacing: "1px" }}>
          ≋ SIMULACIÓN DE BACKTESTING
        </h2>
        
        <div className="card mb">
          <div className="card-head">
            <div className="card-title">CONFIGURACIÓN DE SIMULACIÓN</div>
            {st.params && (
              <span className="chip">
                {st.params.active_strategy === "rsi" ? (
                  `RSI(${st.params.rsi_period})`
                ) : st.params.active_strategy === "wyckoff_1" ? (
                  `Wyckoff(R:${st.params.wyckoff_range_period},V:${st.params.wyckoff_volume_mult})`
                ) : (
                  `BB(${st.params.bb_period},${st.params.bb_std})`
                )} · SL {st.params.active_strategy === "wyckoff_1" ? "Límite Rango" : `${st.params.sl_atr_mult}×ATR(${st.params.atr_period})`} · riesgo {(st.params.risk_per_trade * 100).toFixed(1)}%
              </span>
            )}
          </div>
          <div className="bt-form">
            <label className="bt-field">
              ESTRATEGIA
              <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                <option value="bollinger">Reversión Bollinger</option>
                <option value="rsi">Estrategia RSI</option>
                <option value="wyckoff_1">Método Wyckoff 1</option>
              </select>
            </label>
            <label className="bt-field">
              FUENTE DE DATOS
              <select value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="fxcm" disabled={simulated}>FXCM histórico (real)</option>
                <option value="synthetic">Sintético (prueba)</option>
                <option value="csv">CSV subido</option>
              </select>
            </label>
            <label className="bt-field">
              TIEMPO DE BARRA
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {TF_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <label className="bt-field">
              DESDE
              <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label className="bt-field">
              HASTA
              <input type="date" value={dateTo} min={dateFrom} max={isoDay(new Date())} onChange={(e) => setDateTo(e.target.value)} />
            </label>
            <label className="bt-field">
              EQUITY INICIAL ($)
              <input type="number" min={100} step={100} value={equity} onChange={(e) => setEquity(+e.target.value)} />
            </label>
            <label className="bt-field">
              SPREAD (PIPS)
              <input type="number" min={0} max={10} step={0.1} value={spread} onChange={(e) => setSpread(+e.target.value)} />
            </label>
            <label className="bt-field">
              CSV (OPCIONAL)
              <input
                type="file"
                accept=".csv"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  if (e.target.files?.length) setSource("csv");
                }}
              />
            </label>
            <button className="btn btn-start bt-run" disabled={running} onClick={run}>
              {running ? "EJECUTANDO…" : "EJECUTAR BACKTEST"}
            </button>
          </div>
          <div className={`manual-msg ${btMsg?.cls ?? ""}`}>{btMsg?.text ?? ""}</div>
        </div>

        {done && s && (
          <>
            {st.synthetic ? (
              <div className="bt-banner warn">
                ⚠ DATOS SINTÉTICOS — solo valida el pipeline, no representa el mercado real.
              </div>
            ) : s.trades === 0 ? (
              <div className="bt-banner warn">
                Sin operaciones en el período probado — nada que evaluar.
              </div>
            ) : pfInf || (s.profit_factor ?? 0) >= 1 ? (
              <div className="bt-banner good">
                ✓ EXPECTATIVA POSITIVA en el histórico probado (PF {pfText}). Validar en demo antes de operar.
              </div>
            ) : (
              <div className="bt-banner bad">
                ✗ PROFIT FACTOR {pfText} &lt; 1 — NO operar con estos parámetros; recalibrar en Ajustes.
              </div>
            )}

            <div className="metric-row inner">
              <Metric label="NET PROFIT" val={sign(s.net_profit)} tone={s.net_profit} />
              <Metric label="RETORNO" val={sign(s.return_pct, "%")} tone={s.return_pct} />
              <Metric label="WIN RATE" val={fmt(s.win_rate_pct, 1) + "%"} />
              <Metric label="PROFIT FACTOR" val={pfText} tone={pfInf ? 1 : s.profit_factor == null ? undefined : s.profit_factor - 1} />
            </div>
            <div className="metric-row inner">
              <Metric label="MAX DRAWDOWN" val={fmt(s.max_drawdown_pct, 1) + "%"} tone={s.max_drawdown_pct + 5} />
              <Metric label="TRADES" val={String(s.trades)} />
              <Metric label="PIPS NETOS" val={fmt(s.total_pips, 1)} tone={s.total_pips} />
              <Metric label="AVG TRADE" val={sign(s.avg_trade)} tone={s.avg_trade} />
            </div>

            <div className="card mb" style={{ minHeight: "350px" }}>
              <div className="card-head">
                <div className="card-title">∿ EQUITY DEL BACKTEST</div>
                <span className="chip">
                  {st.source} · {st.timeframe?.toUpperCase()} · {st.period?.from.slice(0, 10)} →{" "}
                  {st.period?.to.slice(0, 10)}
                </span>
              </div>
              <div style={{ height: "300px", width: "100%" }}>
                <AreaChart data={st.equity ?? []} color="#4ade80" fit />
              </div>
            </div>

            <div className="card">
              <div className="card-head">
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
          </>
        )}
      </div>

    </div>
  );
}

function Metric({ label, val, tone }: { label: string; val: string; tone?: number }) {
  return (
    <div className="metric-card">
      <div className="m-lbl">{label}</div>
      <div className={`m-val${tone == null ? "" : tone >= 0 ? " pos" : " neg"}`}>{val}</div>
    </div>
  );
}
