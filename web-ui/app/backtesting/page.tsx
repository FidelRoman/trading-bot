"use client";
/* Backtesting: simular la estrategia sobre histórico con rango de fechas
   y timeframe configurables. El backtest corre en el backend en segundo
   plano; aquí se lanza, se hace polling del estado y se muestran resultados. */

import { useCallback, useEffect, useRef, useState } from "react";
import { AreaChart } from "@/components/charts";
import { getJSON, postJSON } from "@/lib/api";
import { fmt, fmtPx, isoShort, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { BacktestState } from "@/lib/types";

const TF_OPTIONS = [
  { value: "m5", label: "M5 — 5 minutos" },
  { value: "m15", label: "M15 — 15 minutos (el del bot)" },
  { value: "m30", label: "M30 — 30 minutos" },
  { value: "h1", label: "H1 — 1 hora" },
  { value: "h4", label: "H4 — 4 horas" },
  { value: "d1", label: "D1 — diario" },
];

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export default function Backtesting() {
  const { status, backtestVersion } = useLive();
  const simulated = status?.mode === "simulado";

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
  const [msg, setMsg] = useState<{ text: string; cls: string } | null>(null);
  const [st, setSt] = useState<BacktestState>({ status: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getJSON<BacktestState>("/api/backtest");
      setSt(s);
      if (s.status === "running") {
        setMsg({ text: s.note || "Ejecutando…", cls: "" });
        if (!pollRef.current) pollRef.current = setInterval(refresh, 2000);
      } else {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        if (s.status === "error") setMsg({ text: "Error: " + s.error, cls: "err" });
        else if (s.status === "done")
          setMsg({
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
      setMsg({ text: "Subiendo CSV…", cls: "" });
      const fd = new FormData();
      fd.append("file", file);
      const up = await (await fetch("/api/backtest/csv", { method: "POST", body: fd })).json();
      if (!up.ok) { setMsg({ text: "Error subiendo CSV: " + up.error, cls: "err" }); return; }
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
    if (!r.ok) { setMsg({ text: "Error: " + r.error, cls: "err" }); return; }
    setSt({ status: "running" });
    setMsg({ text: "Preparando datos…", cls: "" });
    if (!pollRef.current) pollRef.current = setInterval(refresh, 2000);
  }

  const running = st.status === "running";
  const done = st.status === "done" && st.summary;
  const s = st.summary;
  const pfInf = !!s && s.profit_factor == null && s.trades > 0 && s.net_profit > 0;
  const pfText = pfInf ? "∞" : s?.profit_factor == null ? "—" : fmt(s.profit_factor);

  return (
    <>
      <div className="card mb">
        <div className="card-head">
          <div className="card-title">≋ BACKTESTING — SIMULAR LA ESTRATEGIA SOBRE HISTÓRICO</div>
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
        <div className={`manual-msg ${msg?.cls ?? ""}`}>{msg?.text ?? ""}</div>
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

          <div className="card mb">
            <div className="card-head">
              <div className="card-title">∿ EQUITY DEL BACKTEST</div>
              <span className="chip">
                {st.source} · {st.timeframe?.toUpperCase()} · {st.period?.from.slice(0, 10)} →{" "}
                {st.period?.to.slice(0, 10)}
              </span>
            </div>
            <AreaChart data={st.equity ?? []} color="#4ade80" fit />
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
    </>
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
