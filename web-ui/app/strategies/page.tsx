"use client";
/* ESTRATEGIAS Y SIMULACIÓN

   Antes esto eran tres acordeones casi idénticos —600 líneas repetidas tres
   veces— donde configurar y simular estaban mezclados, no había forma de
   comparar una estrategia con otra, y FSRPPO no aparecía pese a ser
   seleccionable como estrategia activa.

   Ahora: primero la comparación entre las cuatro, después la configuración de
   una sola, y la simulación al lado, en su propio panel. */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AreaChart } from "@/components/charts";
import EmptyState from "@/components/ui/EmptyState";
import Icon from "@/components/ui/Icon";
import Mark from "@/components/ui/Mark";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import Readout from "@/components/ui/Readout";
import Skeleton from "@/components/ui/Skeleton";
import { TableFrame } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { apiFetch, getJSON, postJSON } from "@/lib/api";
import { fmt, fmtPx, isoShort, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { BacktestState, BotSettings } from "@/lib/types";

const TF_OPTIONS = [
  { value: "m5", label: "M5 — 5 minutos" },
  { value: "m15", label: "M15 — 15 minutos" },
  { value: "m30", label: "M30 — 30 minutos" },
  { value: "h1", label: "H1 — 1 hora" },
  { value: "h4", label: "H4 — 4 horas" },
  { value: "d1", label: "D1 — diario" },
];

interface ParamSpec {
  key: keyof BotSettings;
  label: string;
  min: number;
  max: number;
  step?: number;
  note?: string;
}

interface StrategySpec {
  key: string;
  name: string;
  premise: string;
  /** FSRPPO no se configura aquí: sus parámetros son los del entrenamiento. */
  params: ParamSpec[] | null;
}

const SHARED_PARAMS: ParamSpec[] = [
  { key: "atr_period", label: "Período ATR", min: 5, max: 50, step: 1, note: "Velas para medir la volatilidad." },
  { key: "sl_atr_mult", label: "Stop (× ATR)", min: 0.5, max: 5, step: 0.1, note: "Distancia del stop en múltiplos de ATR." },
];

const STRATEGIES: StrategySpec[] = [
  {
    key: "fsrppo",
    name: "FSRPPO — posición neta",
    premise:
      "El agente entrenado decide la posición neta al cierre de cada vela, sobre la señal FSR ya limpia de ruido.",
    params: null,
  },
  {
    key: "bollinger",
    name: "Reversión a la media (Bollinger)",
    premise:
      "Compra en la banda inferior y vende en la superior, asumiendo que el precio vuelve a su media.",
    params: [
      { key: "bb_period", label: "Período Bollinger", min: 10, max: 50, step: 1, note: "Velas de la media móvil." },
      { key: "bb_std", label: "Desviación estándar", min: 1, max: 3, step: 0.1, note: "Ancho de las bandas en sigmas." },
      {
        key: "min_band_width_pips",
        label: "Ancho mínimo de banda (pips)",
        min: 0,
        max: 50,
        step: 1,
        note: "Por debajo de este ancho no opera: el rango es demasiado estrecho para cubrir el spread.",
      },
      ...SHARED_PARAMS,
    ],
  },
  {
    key: "rsi",
    name: "Estrategia RSI",
    premise: "Entra contra el extremo cuando el índice de fuerza relativa marca sobrecompra o sobreventa.",
    params: [
      { key: "rsi_period", label: "Período RSI", min: 5, max: 50, step: 1 },
      { key: "rsi_overbought", label: "Límite de sobrecompra", min: 50, max: 90, step: 1, note: "Por encima, se busca venta." },
      { key: "rsi_oversold", label: "Límite de sobreventa", min: 10, max: 50, step: 1, note: "Por debajo, se busca compra." },
      ...SHARED_PARAMS,
    ],
  },
  {
    key: "wyckoff_1",
    name: "Método Wyckoff 1",
    premise: "Busca la ruptura de un rango de acumulación confirmada por volumen.",
    params: [
      { key: "wyckoff_range_period", label: "Período del rango", min: 5, max: 100, step: 1 },
      { key: "wyckoff_volume_mult", label: "Confirmación por volumen (×)", min: 1, max: 5, step: 0.1, note: "Volumen mínimo respecto a su media para dar la ruptura por buena." },
      { key: "wyckoff_tp_mult", label: "Objetivo (× riesgo)", min: 0.5, max: 10, step: 0.1 },
      ...SHARED_PARAMS,
    ],
  },
];

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

interface SimInputs {
  source: string;
  dateFrom: string;
  dateTo: string;
  equity: number;
  spread: number;
  file: File | null;
  riskPerTrade: number;
  fixedUnits: number;
}

const defaultSim = (risk = 0.5, fixed = 0): SimInputs => ({
  source: "synthetic",
  dateFrom: isoDay(new Date(Date.now() - 730 * 86400_000)),
  dateTo: isoDay(new Date()),
  equity: 10000,
  spread: 1.2,
  file: null,
  riskPerTrade: risk,
  fixedUnits: fixed,
});

export default function StrategiesPage() {
  const { status, backtestVersion, refreshStatus } = useLive();
  const { push } = useToast();
  const activeStrategy = status?.active_strategy || "bollinger";
  const simulated = status?.mode === "simulado";

  const [values, setValues] = useState<Record<string, number | string>>({});
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<string>("bollinger");
  const [sim, setSim] = useState<SimInputs>(defaultSim());
  const [results, setResults] = useState<Record<string, BacktestState>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [runNote, setRunNote] = useState<string>("");
  const [showTrades, setShowTrades] = useState(false);
  const [saving, setSaving] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const spec = STRATEGIES.find((s) => s.key === selected) ?? STRATEGIES[1];
  const result = results[selected];

  useEffect(() => {
    getJSON<BotSettings>("/api/settings")
      .then((s) => {
        setValues({ ...(s as unknown as Record<string, number | string>) });
        if (s.active_strategy) setSelected(s.active_strategy);
        setSim(defaultSim(s.risk_per_trade ? +(s.risk_per_trade * 100).toFixed(2) : 0.5, s.fixed_units ?? 0));
        setLoaded(true);
      })
      .catch(() => {
        push("No se pudieron cargar los parámetros de las estrategias.", "danger");
        setLoaded(true);
      });

    getJSON<BacktestState>("/api/backtest")
      .then((s) => {
        if (s && s.status === "done" && s.params?.active_strategy)
          setResults({ [s.params.active_strategy]: s });
      })
      .catch(() => {});
  }, [push]);

  const refresh = useCallback(async () => {
    try {
      const s = await getJSON<BacktestState>("/api/backtest");
      if (s.status === "queued" || s.status === "running") {
        setRunNote(s.note || (s.status === "queued" ? "En cola…" : "Ejecutando…"));
        if (!pollRef.current) pollRef.current = setInterval(refresh, 5000);
        return;
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      const key = s.params?.active_strategy || running;
      if (key) {
        setResults((prev) => ({ ...prev, [key]: s }));
        if (s.status === "error") push(s.error ?? "La simulación falló.", "danger");
        else if (s.status === "done" && running)
          push(`Simulación terminada: ${s.candles} velas (${s.source}).`);
        if (running === key) setRunning(null);
      }
      setRunNote("");
    } catch {
      /* backend caído: el polling de live ya avisa */
    }
  }, [running, push]);

  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh, backtestVersion]);

  // En simulado no hay histórico real que pedir al bróker.
  useEffect(() => {
    if (simulated && sim.source === "fxcm") setSim((prev) => ({ ...prev, source: "synthetic" }));
  }, [simulated, sim.source]);

  async function save() {
    if (!spec.params) return;
    setSaving(true);
    const payload: Record<string, unknown> = { timeframe: values.timeframe || "m15" };
    for (const field of spec.params) payload[field.key] = values[field.key];
    try {
      const r = await postJSON<{ ok: boolean; settings: BotSettings; error?: string }>(
        "/api/settings",
        payload
      );
      if (!r.ok) throw new Error(r.error ?? "No se pudieron guardar los parámetros.");
      setValues({ ...(r.settings as unknown as Record<string, number | string>) });
      push("Parámetros guardados.");
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudieron guardar.", "danger");
    } finally {
      setSaving(false);
    }
  }

  async function activate(key: string) {
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/settings", {
        active_strategy: key,
      });
      if (!r.ok) throw new Error(r.error ?? "No se pudo activar la estrategia.");
      await refreshStatus();
      push(`${STRATEGIES.find((s) => s.key === key)?.name} es ahora la estrategia activa.`);
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudo activar.", "danger");
    }
  }

  async function runSimulation() {
    setRunning(selected);
    setRunNote("Preparando datos…");
    try {
      if (sim.source === "csv" && sim.file) {
        setRunNote("Subiendo CSV…");
        const body = new FormData();
        body.append("file", sim.file);
        const up = await (await apiFetch("/api/backtest/csv", { method: "POST", body })).json();
        if (!up.ok) throw new Error(`No se pudo subir el CSV: ${up.error}`);
      }
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/backtest", {
        source: sim.source,
        timeframe: values.timeframe || "m15",
        date_from: sim.dateFrom,
        date_to: sim.dateTo,
        equity: sim.equity,
        spread_pips: sim.spread,
        strategy: selected,
        strategy_params: values,
        risk_per_trade: sim.riskPerTrade ? sim.riskPerTrade / 100 : undefined,
        fixed_units: sim.fixedUnits || 0,
      });
      if (!r.ok) throw new Error(r.error ?? "No se pudo lanzar la simulación.");
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudo lanzar la simulación.", "danger");
      setRunning(null);
      setRunNote("");
    }
  }

  return (
    <div className="stack">
      {/* ---------------- comparación ---------------- */}
      <Panel
        label="Las cuatro estrategias"
        bleed
        caption="Cada fila resume la última simulación que se lanzó desde aquí. FSRPPO no se simula en esta página: sus resultados fuera de muestra se miden al entrenar y se comparan en Modelos."
      >
        <TableFrame>
          <table>
            <thead>
              <tr>
                <th>Estrategia</th>
                <th>Estado</th>
                <th className="num">Operaciones</th>
                <th className="num">Retorno</th>
                <th className="num">Profit factor</th>
                <th className="num">Caída máx.</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {STRATEGIES.map((item) => {
                const summary = results[item.key]?.summary;
                const isActive = activeStrategy === item.key;
                return (
                  <tr key={item.key} className={isActive ? "is-marked" : undefined}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{item.name}</div>
                      <div style={{ color: "var(--ink-3)", fontSize: "var(--fs-2xs)" }}>
                        {item.premise}
                      </div>
                    </td>
                    <td>{isActive ? <Mark tone="ok" dot>Activa</Mark> : <span className="muted">En reserva</span>}</td>
                    <td className="num">{summary ? summary.trades : "—"}</td>
                    <td className={`num ${summary && summary.return_pct >= 0 ? "pos" : summary ? "neg" : ""}`}>
                      {summary ? sign(summary.return_pct, "%") : "—"}
                    </td>
                    <td className="num">
                      {summary
                        ? summary.profit_factor == null
                          ? summary.net_profit > 0 && summary.trades > 0
                            ? "∞"
                            : "—"
                          : fmt(summary.profit_factor)
                        : "—"}
                    </td>
                    <td className="num">{summary ? `${fmt(summary.max_drawdown_pct, 1)}%` : "—"}</td>
                    <td>
                      {item.key === "fsrppo" ? (
                        <Link href="/models">Ver modelos</Link>
                      ) : isActive ? (
                        <button className="btn" onClick={() => setSelected(item.key)}>
                          Configurar
                        </button>
                      ) : (
                        <button className="btn" onClick={() => activate(item.key)}>
                          Activar
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableFrame>
      </Panel>

      {/* ---------------- selección ---------------- */}
      <div className="seg" role="tablist" aria-label="Estrategia a configurar">
        {STRATEGIES.map((item) => (
          <button
            key={item.key}
            role="tab"
            type="button"
            aria-selected={selected === item.key}
            onClick={() => setSelected(item.key)}
          >
            {item.name.split(" —")[0].split(" (")[0]}
          </button>
        ))}
      </div>

      {!spec.params ? (
        <Panel label={spec.name}>
          <Notice tone="info" title="FSRPPO no se configura aquí.">
            Sus parámetros son los del entrenamiento (iteraciones, learning rate, entropía,
            exposición máxima) y quedan fijados dentro de cada modelo.{" "}
            <Link href="/train">Entrenar un modelo</Link> ·{" "}
            <Link href="/models">Comparar y activar modelos</Link>
          </Notice>
        </Panel>
      ) : (
        <div className="plate halves">
          <div className="stack">
            <Panel
              label="Parámetros"
              actions={
                activeStrategy === spec.key ? (
                  <Mark tone="ok" dot>
                    Activa
                  </Mark>
                ) : (
                  <button className="btn quiet" onClick={() => activate(spec.key)}>
                    Activar esta
                  </button>
                )
              }
              caption={spec.premise}
            >
              {!loaded ? (
                <Skeleton height={30} count={5} />
              ) : (
                <>
                  <div className="field-grid">
                    <div className="field">
                      <label className="field-label" htmlFor="tf">
                        Temporalidad
                      </label>
                      <select
                        id="tf"
                        className="select"
                        value={(values.timeframe as string) ?? "m15"}
                        onChange={(e) => setValues({ ...values, timeframe: e.target.value })}
                      >
                        {TF_OPTIONS.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                      <span className="field-note">Tamaño de vela con el que decide.</span>
                    </div>
                    {spec.params.map((field) => (
                      <div className="field" key={String(field.key)}>
                        <label className="field-label" htmlFor={String(field.key)}>
                          {field.label}
                        </label>
                        <input
                          id={String(field.key)}
                          className="input"
                          type="number"
                          min={field.min}
                          max={field.max}
                          step={field.step ?? 1}
                          value={(values[field.key] as number) ?? ""}
                          onChange={(e) =>
                            setValues({ ...values, [field.key]: +e.target.value })
                          }
                        />
                        <span className="field-note">
                          {field.note ? `${field.note} ` : ""}
                          Entre {field.min} y {field.max}.
                        </span>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: "var(--s-5)" }}>
                    <button className="btn primary" onClick={save} disabled={saving}>
                      {saving ? "Guardando…" : "Guardar parámetros"}
                    </button>
                  </div>
                </>
              )}
            </Panel>

            <Panel
              label="Datos de la simulación"
              caption="La simulación usa los parámetros de arriba tal y como están en el formulario, aunque no se hayan guardado."
            >
              <div className="field-grid">
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label className="field-label" htmlFor="sim-source">
                    Fuente de datos
                  </label>
                  <select
                    id="sim-source"
                    className="select"
                    value={sim.source}
                    onChange={(e) => setSim({ ...sim, source: e.target.value })}
                  >
                    <option value="fxcm" disabled={simulated}>
                      Histórico de FXCM
                    </option>
                    <option value="synthetic">Sintético (prueba del pipeline)</option>
                    <option value="csv">CSV subido</option>
                  </select>
                  {simulated && (
                    <span className="field-note">
                      En modo simulado no hay sesión con el bróker: solo sintético o CSV.
                    </span>
                  )}
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-from">
                    Desde
                  </label>
                  <input
                    id="sim-from"
                    className="input"
                    type="date"
                    value={sim.dateFrom}
                    max={sim.dateTo}
                    onChange={(e) => setSim({ ...sim, dateFrom: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-to">
                    Hasta
                  </label>
                  <input
                    id="sim-to"
                    className="input"
                    type="date"
                    value={sim.dateTo}
                    min={sim.dateFrom}
                    max={isoDay(new Date())}
                    onChange={(e) => setSim({ ...sim, dateTo: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-equity">
                    Capital inicial ($)
                  </label>
                  <input
                    id="sim-equity"
                    className="input"
                    type="number"
                    min={100}
                    step={100}
                    value={sim.equity}
                    onChange={(e) => setSim({ ...sim, equity: +e.target.value })}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-spread">
                    Spread asumido (pips)
                  </label>
                  <input
                    id="sim-spread"
                    className="input"
                    type="number"
                    min={0}
                    max={10}
                    step={0.1}
                    value={sim.spread}
                    onChange={(e) => setSim({ ...sim, spread: +e.target.value })}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-risk">
                    Riesgo por operación (%)
                  </label>
                  <input
                    id="sim-risk"
                    className="input"
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={sim.riskPerTrade}
                    disabled={sim.fixedUnits > 0}
                    onChange={(e) => setSim({ ...sim, riskPerTrade: +e.target.value })}
                  />
                  <span className="field-note">
                    {sim.fixedUnits > 0 ? "Inerte: mandan las unidades fijas." : "Dimensiona cada orden."}
                  </span>
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="sim-units">
                    Unidades fijas
                  </label>
                  <input
                    id="sim-units"
                    className="input"
                    type="number"
                    min={0}
                    step={1000}
                    value={sim.fixedUnits}
                    onChange={(e) => setSim({ ...sim, fixedUnits: +e.target.value })}
                  />
                  <span className="field-note">0 = tamaño automático por riesgo.</span>
                </div>
                {sim.source === "csv" && (
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label className="field-label" htmlFor="sim-csv">
                      Archivo CSV
                    </label>
                    <input
                      id="sim-csv"
                      className="input"
                      type="file"
                      accept=".csv"
                      onChange={(e) => setSim({ ...sim, file: e.target.files?.[0] ?? null })}
                    />
                  </div>
                )}
              </div>
              <div style={{ marginTop: "var(--s-5)" }}>
                <button
                  className="btn primary lg block"
                  disabled={running !== null}
                  onClick={runSimulation}
                >
                  {running ? "Simulando…" : "Ejecutar simulación"}
                </button>
                {runNote && (
                  <p className="field-note" style={{ marginTop: "var(--s-2)" }} role="status">
                    {runNote}
                  </p>
                )}
              </div>
            </Panel>
          </div>

          {/* ---------------- resultado ---------------- */}
          <div className="stack">
            <SimulationResult
              state={result}
              running={running === selected}
              note={runNote}
              showTrades={showTrades}
              onToggleTrades={() => setShowTrades((v) => !v)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SimulationResult({
  state,
  running,
  note,
  showTrades,
  onToggleTrades,
}: {
  state?: BacktestState;
  running: boolean;
  note: string;
  showTrades: boolean;
  onToggleTrades: () => void;
}) {
  if (running) {
    return (
      <Panel label="Resultado de la simulación">
        <div style={{ display: "grid", gap: "var(--s-4)" }}>
          <p className="field-note" role="status" aria-live="polite">
            {note || "Ejecutando…"}
          </p>
          <Skeleton height={22} count={2} />
          <Skeleton height={140} />
        </div>
      </Panel>
    );
  }

  const summary = state?.summary;
  if (!state || !summary) {
    return (
      <Panel label="Resultado de la simulación" bleed>
        <EmptyState
          title="Sin simulación todavía"
          hint="Ajusta los datos de la izquierda y ejecuta la simulación para ver cómo se habría comportado esta estrategia sobre el período elegido."
        />
      </Panel>
    );
  }

  const infinitePf = summary.profit_factor == null && summary.trades > 0 && summary.net_profit > 0;
  const pf = infinitePf ? "∞" : summary.profit_factor == null ? "—" : fmt(summary.profit_factor);

  return (
    <>
      <Panel
        label="Resultado de la simulación"
        actions={
          state.finished ? (
            <span className="field-note">
              {isoShort(state.finished)} UTC · {state.candles} velas
            </span>
          ) : undefined
        }
        caption={
          state.period
            ? `Período simulado: ${state.period.from} → ${state.period.to}, fuente ${state.source}.`
            : undefined
        }
      >
        <div style={{ display: "grid", gap: "var(--s-4)" }}>
          {state.synthetic ? (
            <Notice tone="warn" title="Datos sintéticos.">
              Sirven para comprobar que el pipeline funciona, no para juzgar la estrategia.
            </Notice>
          ) : summary.trades === 0 ? (
            <Notice tone="warn" title="Sin operaciones en el período.">
              Los filtros de la estrategia no dieron ninguna entrada. Prueba a relajarlos o a
              ampliar el rango de fechas.
            </Notice>
          ) : infinitePf || (summary.profit_factor ?? 0) >= 1 ? (
            <Notice tone="ok" title={`Expectativa positiva (profit factor ${pf}).`}>
              Sobre este período y con este spread. Un solo tramo no es evidencia.
            </Notice>
          ) : (
            <Notice tone="danger" title={`Expectativa negativa (profit factor ${pf}).`}>
              La estrategia habría perdido dinero en este período con estos parámetros.
            </Notice>
          )}

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: "var(--s-4)",
            }}
          >
            <Readout label="Beneficio neto" value={sign(summary.net_profit)} tone={summary.net_profit >= 0 ? "pos" : "neg"} />
            <Readout label="Retorno" value={sign(summary.return_pct, "%")} tone={summary.return_pct >= 0 ? "pos" : "neg"} />
            <Readout label="Aciertos" value={`${fmt(summary.win_rate_pct, 1)}%`} />
            <Readout label="Profit factor" value={pf} />
            <Readout label="Caída máxima" value={`${fmt(summary.max_drawdown_pct, 1)}%`} tone={summary.max_drawdown_pct <= -5 ? "neg" : "none"} />
            <Readout label="Operaciones" value={String(summary.trades)} />
            <Readout label="Pips netos" value={fmt(summary.total_pips, 1)} tone={summary.total_pips >= 0 ? "pos" : "neg"} />
            <Readout label="Media por operación" value={sign(summary.avg_trade)} tone={summary.avg_trade >= 0 ? "pos" : "neg"} />
          </div>
        </div>
      </Panel>

      <Panel label="Curva de capital simulada" bleed>
        <div style={{ padding: "var(--s-2)" }}>
          <AreaChart
            data={state.equity ?? []}
            tone={summary.net_profit >= 0 ? "long" : "short"}
            fit
            short
            label="Curva de capital de la simulación"
          />
        </div>
      </Panel>

      <Panel
        label="Operaciones de la simulación"
        count={state.trades?.length ?? 0}
        actions={
          <button className="btn quiet" onClick={onToggleTrades} aria-expanded={showTrades}>
            <Icon name={showTrades ? "close" : "compare"} size={13} />
            {showTrades ? "Ocultar" : "Mostrar"}
          </button>
        }
        bleed={showTrades}
      >
        {showTrades ? (
          <TableFrame maxHeight={420}>
            <table>
              <thead>
                <tr>
                  <th>Dirección</th>
                  <th className="num">Unidades</th>
                  <th className="num">Entrada</th>
                  <th className="num">Salida</th>
                  <th className="num">Pips</th>
                  <th className="num">P&L</th>
                  <th>Motivo</th>
                  <th>Fecha</th>
                </tr>
              </thead>
              <tbody>
                {(state.trades ?? [])
                  .slice()
                  .reverse()
                  .map((t, i) => (
                    <tr key={i}>
                      <td className={t.side === "long" ? "pos" : "neg"}>
                        {t.side === "long" ? "Compra" : "Venta"}
                      </td>
                      <td className="num">{fmt(t.units, 0)}</td>
                      <td className="num">{fmtPx(t.entry)}</td>
                      <td className="num">{fmtPx(t.exit)}</td>
                      <td className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}>{fmt(t.pips, 1)}</td>
                      <td className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}>{sign(t.pnl)}</td>
                      <td>{t.reason ?? "—"}</td>
                      <td>{isoShort(t.exit_time)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </TableFrame>
        ) : (
          <p className="field-note">
            Las {state.trades?.length ?? 0} operaciones que produjo esta simulación, con su motivo
            de cierre.
          </p>
        )}
      </Panel>
    </>
  );
}
