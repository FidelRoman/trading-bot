"use client";
/* Entrenamiento de FSRPPO: lanzar un run, seguirlo en vivo y ver si el
   resultado fuera de muestra bate a comprar-y-mantener. */

import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { MetricsHead, MetricsRow } from "@/components/metrics";
import { useLive } from "@/lib/live";
import type { InstrumentSpec, TrainingCurvePoint, TrainingState } from "@/lib/types";

interface DatasetInfo { name: string; size: number }

/** `EUR/USD` → `eurusd`, que es como `download_history.py` nombra los CSV. */
function slug(symbol: string): string {
  return symbol.replace("/", "").toLowerCase();
}

const CAMPOS = [
  { key: "iterations", label: "ITERACIONES (NI)", def: 200, min: 1, max: 2000, step: 1 },
  { key: "seed", label: "SEMILLA", def: 0, min: 0, max: 9999, step: 1 },
  { key: "learning_rate", label: "LEARNING RATE", def: 0.00001, min: 1e-6, max: 0.01, step: 1e-6 },
  { key: "entropy_coef", label: "ENTROPÍA (c)", def: 0.01, min: 0, max: 0.5, step: 0.001 },
  { key: "max_units", label: "EXPOSICIÓN MÁX. (uds)", def: 20000, min: 1000, max: 1000000, step: 1000 },
  { key: "spread_pips", label: "SPREAD (pips)", def: 1.2, min: 0, max: 10, step: 0.1 },
] as const;

/** Curva de una serie del historial de entrenamiento. */
function Curve({ points, pick, color, label }: {
  points: TrainingCurvePoint[];
  pick: (p: TrainingCurvePoint) => number;
  color: string;
  label: string;
}) {
  const serie = points.map(pick).filter(Number.isFinite);
  if (serie.length < 2) return <div className="empty">Sin datos de {label}</div>;

  const min = Math.min(...serie);
  const max = Math.max(...serie);
  const span = max - min || 1;
  const h = 120;
  const pts = serie
    .map((v, i) => `${((i / (serie.length - 1)) * 100).toFixed(2)},${(h - ((v - min) / span) * h).toFixed(2)}`)
    .join(" ");

  return (
    <div>
      <div className="hint" style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{label}</span>
        <span>{min.toFixed(2)} … {max.toFixed(2)}</span>
      </div>
      <svg viewBox={`0 0 100 ${h}`} preserveAspectRatio="none"
           style={{ width: "100%", height: h, display: "block" }}>
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.4"
                  vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

export default function TrainPage() {
  const { status } = useLive();
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentSpec[]>([]);
  const [job, setJob] = useState<TrainingState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, number>>(
    Object.fromEntries(CAMPOS.map((c) => [c.key, c.def]))
  );
  const [dataset, setDataset] = useState("");
  // Cada modelo se entrena para un instrumento y su ficha (pip, lote, spread)
  // queda dentro: es lo que luego dimensiona las órdenes al operarlo.
  const [instrumento, setInstrumento] = useState("");
  const [timeframe, setTimeframe] = useState("h1");
  const [trainEnd, setTrainEnd] = useState("");
  const [activar, setActivar] = useState(false);
  const [years, setYears] = useState(3);

  useEffect(() => {
    getJSON<{ datasets: DatasetInfo[] }>("/api/training/datasets")
      .then((r) => {
        setDatasets(r.datasets);
        if (r.datasets.length) setDataset(r.datasets[0].name);
      })
      .catch(() => {});
    getJSON<{ instruments: InstrumentSpec[] }>("/api/instruments")
      .then((r) => setInstrumentos(r.instruments))
      .catch(() => setInstrumentos([]));
  }, []);

  // Por defecto, el instrumento que opera el bot: es el caso normal.
  useEffect(() => {
    if (!instrumento && status?.instrument) setInstrumento(status.instrument);
  }, [status?.instrument, instrumento]);

  useEffect(() => {
    const leer = () => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {});
    leer();
    const t = setInterval(leer, 2000);
    return () => clearInterval(t);
  }, []);

  const lanzar = async () => {
    setError(null);
    const r = await postJSON<{ ok: boolean; error?: string }>("/api/training", {
      dataset, timeframe, instrument: instrumento,
      train_end: trainEnd || null, activate: activar, ...form,
    });
    if (!r.ok) setError(r.error ?? "No se pudo lanzar el entrenamiento");
    else setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
  };

  const descargar = async () => {
    setError(null);
    const r = await postJSON<{ ok: boolean; error?: string }>("/api/training/download", {
      symbol: instrumento, timeframe, years,
    });
    if (!r.ok) setError(r.error ?? "No se pudo lanzar la descarga");
    else setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
  };

  // Al acabar una descarga hay un CSV nuevo: se recarga la lista y se preselecciona.
  useEffect(() => {
    if (job?.status !== "done" || job?.kind !== "download") return;
    getJSON<{ datasets: DatasetInfo[] }>("/api/training/datasets")
      .then((r) => {
        setDatasets(r.datasets);
        if (job.dataset) setDataset(job.dataset);
      })
      .catch(() => {});
  }, [job?.status, job?.kind, job?.dataset]);

  const corriendo = job?.status === "running";
  // Los CSV se llaman <slug>_<tf>_<desde>_<hasta>.csv. Entrenar EUR/USD con el
  // histórico del oro produce un modelo mal etiquetado que nadie detecta después.
  const desajuste = !!dataset && !!instrumento && !dataset.startsWith(`${slug(instrumento)}_`);
  const curva = useMemo(() => job?.curve ?? [], [job]);
  const bateReferencia =
    job?.test_metrics?.crr != null && job?.benchmark_metrics?.crr != null &&
    job.test_metrics.crr > job.benchmark_metrics.crr &&
    (job.test_metrics.sharpe ?? -1) > 0;

  return (
    <>
      <div className="card">
        <div className="card-head">
          <div className="card-title">⤓ DESCARGAR HISTÓRICO</div>
          <button className="btn" onClick={descargar} disabled={corriendo || !instrumento}>
            {corriendo ? "EN CURSO…" : "DESCARGAR"}
          </button>
        </div>
        <div className="form-grid" style={{ padding: 12 }}>
          <label>
            <span>INSTRUMENTO</span>
            <select value={instrumento} onChange={(e) => setInstrumento(e.target.value)}>
              {!instrumentos.some((i) => i.symbol === instrumento) && instrumento && (
                <option value={instrumento}>{instrumento}</option>
              )}
              {instrumentos.map((i) => (
                <option key={i.symbol} value={i.symbol}>{i.symbol}</option>
              ))}
            </select>
          </label>
          <label>
            <span>TIMEFRAME</span>
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {["m15", "m30", "h1", "h4", "d1"].map((t) => (
                <option key={t} value={t}>{t.toUpperCase()}</option>
              ))}
            </select>
          </label>
          <label>
            <span>AÑOS DE HISTÓRICO</span>
            <input type="number" min={1} max={10} step={1} value={years}
                   onChange={(e) => setYears(Number(e.target.value))} />
          </label>
        </div>
        <div className="hint" style={{ padding: "0 12px 12px" }}>
          Va por la sesión FXCM que el bot ya tiene abierta: no abre un segundo
          login ni cambia el instrumento que opera. El archivo queda en{" "}
          <code>data/history/</code> y se selecciona solo abajo al terminar; es el
          mismo resultado que <code>scripts/download_history.py</code>. Bajar
          años de M15 o M30 tarda bastante más que de H4 o D1, y mientras tanto no
          se puede lanzar un entrenamiento.
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">◈ NUEVO ENTRENAMIENTO</div>
          <button className="btn primary" onClick={lanzar} disabled={corriendo || !dataset}>
            {corriendo ? "EN CURSO…" : "ENTRENAR"}
          </button>
        </div>

        <div className="hint" style={{ padding: "10px 12px 0" }}>
          Se entrenará <strong>{instrumento || "—"}</strong> en{" "}
          <strong>{timeframe.toUpperCase()}</strong>, según lo elegido arriba.
        </div>

        <div className="form-grid" style={{ padding: 12 }}>
          <label>
            <span>HISTÓRICO</span>
            <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
              {datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
          </label>
          <label>
            <span>FIN DE TRAIN (vacío = 75%)</span>
            <input type="date" value={trainEnd} onChange={(e) => setTrainEnd(e.target.value)} />
          </label>

          {CAMPOS.map((c) => (
            <label key={c.key}>
              <span>{c.label}</span>
              <input
                type="number" min={c.min} max={c.max} step={c.step}
                value={form[c.key]}
                onChange={(e) => setForm({ ...form, [c.key]: Number(e.target.value) })}
              />
            </label>
          ))}

          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={activar} onChange={(e) => setActivar(e.target.checked)} />
            <span>Activar al terminar</span>
          </label>
        </div>

        {desajuste && (
          <div className="picker-warn" style={{ margin: "0 12px 10px" }}>
            El histórico <strong>{dataset}</strong> no parece de{" "}
            <strong>{instrumento}</strong>. El modelo quedaría etiquetado con un
            instrumento y entrenado con los precios de otro, y al operarlo se
            dimensionaría con la ficha equivocada. Descarga el histórico correcto
            con <code>scripts/download_history.py --symbols {instrumento}</code>.
          </div>
        )}

        <div className="hint" style={{ padding: "0 12px 12px" }}>
          El modelo queda ligado al instrumento elegido: al operar, el bot arma el
          modelo activo del símbolo que tenga puesto. El tramo de test no
          interviene en el entrenamiento, solo se mide al final. Si las
          características FSR de este histórico no están cacheadas, se calculan
          primero y eso tarda bastante.
          {datasets.length === 0 && (
            <> <strong>No hay ningún histórico descargado</strong>: bájalo antes
            con <code>uv run python scripts/download_history.py --symbols {instrumento || "EUR/USD"} --timeframes {timeframe} --years 3</code>.</>
          )}
        </div>
        {error && <div className="empty neg">{error}</div>}
      </div>

      {corriendo && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              ⟳ {job?.kind === "precompute" ? "PRECALCULANDO FSR"
                 : job?.kind === "download" ? "DESCARGANDO HISTÓRICO"
                 : "ENTRENANDO"}
            </div>
            <span className="chip">{Math.round((job?.progress ?? 0) * 100)}%</span>
          </div>
          <div style={{ padding: "0 12px 12px" }}>
            <div style={{ height: 6, background: "rgba(148,163,184,.15)", borderRadius: 3 }}>
              <div style={{
                width: `${(job?.progress ?? 0) * 100}%`, height: "100%",
                background: "#4ade80", borderRadius: 3, transition: "width .4s",
              }} />
            </div>
            <div className="hint" style={{ marginTop: 6 }}>{job?.note}</div>
          </div>
          {curva.length > 1 && (
            <div style={{ padding: 12, display: "grid", gap: 16 }}>
              <Curve points={curva} pick={(p) => p.mean_reward} color="#4ade80"
                     label="Recompensa media por episodio" />
              <Curve points={curva} pick={(p) => p.entropy} color="#60a5fa"
                     label="Entropía de la política (exploración)" />
            </div>
          )}
        </div>
      )}

      {job?.status === "error" && (
        <div className="card">
          <div className="card-head"><div className="card-title">✕ ERROR</div></div>
          <div className="empty neg">{job.error}</div>
        </div>
      )}

      {job?.status === "done" && job.kind === "download" && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">✓ HISTÓRICO DESCARGADO</div>
            <span className="chip">{job.elapsed_s}s</span>
          </div>
          <div className="hint" style={{ padding: 12 }}>
            <strong>{job.dataset}</strong> — {job.bars?.toLocaleString("es")} velas de{" "}
            {job.symbol} {job.timeframe?.toUpperCase()},
            de {job.first_bar?.slice(0, 10)} a {job.last_bar?.slice(0, 10)}.
            Ya está seleccionado abajo como histórico del entrenamiento.
          </div>
        </div>
      )}

      {job?.status === "done" && job.kind === "training" && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">✓ RESULTADO — {job.run_id}</div>
            <span className="chip">{job.elapsed_s}s</span>
          </div>
          <div className="table-wrap">
            <table>
              <MetricsHead />
              <tbody>
                <MetricsRow name="Buy &amp; Hold (test)" metrics={job.benchmark_metrics} />
                <MetricsRow name="FSRPPO (test)" metrics={job.test_metrics}
                            reference={job.benchmark_metrics} highlight />
                <MetricsRow name="FSRPPO (train)" metrics={job.train_metrics} />
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ padding: "8px 12px" }}>
            {bateReferencia
              ? "Este run bate a comprar-y-mantener con Sharpe positivo fuera de muestra. Un solo run no es evidencia: hay que repetir con varias semillas antes de activarlo."
              : "Este run NO supera a comprar-y-mantener fuera de muestra. Comparar train contra test indica si es falta de aprendizaje o sobreajuste."}
          </div>
          {(job.curve?.length ?? 0) > 1 && (
            <div style={{ padding: 12, display: "grid", gap: 16 }}>
              <Curve points={job.curve!} pick={(p) => p.mean_reward} color="#4ade80"
                     label="Recompensa media por episodio" />
              <Curve points={job.curve!} pick={(p) => p.value_loss} color="#fbbf24"
                     label="Pérdida de la red de valor" />
            </div>
          )}
        </div>
      )}
    </>
  );
}
