"use client";
/* Entrenamiento de FSRPPO: lanzar un run, seguirlo en vivo y ver si el
   resultado fuera de muestra bate a comprar-y-mantener.

   Los seis hiperparámetros iban antes en una rejilla plana sin decir qué hacía
   ninguno ni qué rango tenía sentido. Ahora van por etapa —cuánto entrena, qué
   arriesga cada decisión, cuánto cuesta operar— y cada uno lleva su nota. */

import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { MetricsHead, MetricsRow } from "@/components/metrics";
import EmptyState from "@/components/ui/EmptyState";
import Mark from "@/components/ui/Mark";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { TableFrame } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { useLive } from "@/lib/live";
import type { InstrumentSpec, TrainingCurvePoint, TrainingState } from "@/lib/types";

interface DatasetInfo {
  name: string;
  size: number;
}

/** `EUR/USD` → `eurusd`, que es como `download_history.py` nombra los CSV. */
function slug(symbol: string): string {
  return symbol.replace("/", "").toLowerCase();
}

interface Campo {
  key: string;
  label: string;
  def: number;
  min: number;
  max: number;
  step: number;
  note: string;
}

const GRUPOS: { title: string; caption: string; fields: Campo[] }[] = [
  {
    title: "Cuánto aprende",
    caption: "Más iteraciones es más tiempo de cálculo, no necesariamente mejor política.",
    fields: [
      {
        key: "iterations",
        label: "Iteraciones",
        def: 200,
        min: 1,
        max: 2000,
        step: 1,
        note: "Pasadas completas de PPO sobre el tramo de train.",
      },
      {
        key: "learning_rate",
        label: "Learning rate",
        def: 0.00001,
        min: 1e-6,
        max: 0.01,
        step: 1e-6,
        note: "Con 1e-5, el del paper, el agente no llega a operar en FX: hace falta subirlo.",
      },
      {
        key: "entropy_coef",
        label: "Entropía (c)",
        def: 0.01,
        min: 0,
        max: 0.5,
        step: 0.001,
        note: "Cuánto se le paga por explorar. A cero converge pronto y se queda quieto.",
      },
      {
        key: "seed",
        label: "Semilla",
        def: 0,
        min: 0,
        max: 9999,
        step: 1,
        note: "Un run no es evidencia: repite con varias semillas antes de activar nada.",
      },
    ],
  },
  {
    title: "Cuánto cuesta operar",
    caption: "Define el entorno en el que aprende: si no se parece al real, lo aprendido no sirve.",
    fields: [
      {
        key: "spread_pips",
        label: "Spread asumido (pips)",
        def: 1.2,
        min: 0,
        max: 10,
        step: 0.1,
        note: "El coste de operar. Ponerlo bajo produce modelos que solo ganan en el papel.",
      },
    ],
  },
];

const CAMPOS = GRUPOS.flatMap((g) => g.fields);

/** Curva de una serie del historial de entrenamiento. */
function Curve({
  points,
  pick,
  tone,
  label,
}: {
  points: TrainingCurvePoint[];
  pick: (p: TrainingCurvePoint) => number;
  tone: "long" | "accent" | "warn";
  label: string;
}) {
  const serie = points.map(pick).filter(Number.isFinite);
  if (serie.length < 2) return <EmptyState title={`Sin datos de ${label.toLowerCase()}`} />;

  const min = Math.min(...serie);
  const max = Math.max(...serie);
  const span = max - min || 1;
  const h = 120;
  const pts = serie
    .map((v, i) => `${((i / (serie.length - 1)) * 100).toFixed(2)},${(h - ((v - min) / span) * h).toFixed(2)}`)
    .join(" ");

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "var(--fs-eje)",
          color: "var(--ink-3)",
          textTransform: "uppercase",
          letterSpacing: "var(--tracking-eje)",
          marginBottom: "var(--s-1)",
        }}
      >
        <span>{label}</span>
        <span className="num">
          {min.toFixed(2)} … {max.toFixed(2)}
        </span>
      </div>
      <svg
        viewBox={`0 0 100 ${h}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: mínimo ${min.toFixed(2)}, máximo ${max.toFixed(2)}, ${serie.length} puntos`}
        style={{
          width: "100%",
          height: h,
          display: "block",
          borderBottom: "1px solid var(--rule)",
          borderLeft: "1px solid var(--rule)",
        }}
      >
        <polyline
          points={pts}
          fill="none"
          stroke={`var(--${tone})`}
          strokeWidth="1.4"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

export default function TrainPage() {
  const { status } = useLive();
  const { push } = useToast();
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentSpec[]>([]);
  const [job, setJob] = useState<TrainingState | null>(null);
  const [form, setForm] = useState<Record<string, number>>(
    Object.fromEntries(CAMPOS.map((c) => [c.key, c.def]))
  );
  const [dataset, setDataset] = useState("");
  // Cada modelo se entrena para un instrumento y su ficha (pip, lote, spread)
  // queda dentro: es lo que luego dimensiona las órdenes al operarlo.
  const [instrumento, setInstrumento] = useState("");
  const [timeframe, setTimeframe] = useState("h1");
  const [trainEnd, setTrainEnd] = useState("");
  // Vacío = automático: el backend deriva el techo de posición del precio real
  // del instrumento (~2:1 sobre capital). Un valor fijo aquí, aplicado por igual
  // a EUR/USD y a XAU/USD, sobreexpuso el oro ~3000x y produjo un modelo que
  // nunca operó — ver el mismo arreglo en scripts/train_fsrppo.py.
  const [maxUnits, setMaxUnits] = useState("");
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
    const r = await postJSON<{ ok: boolean; error?: string }>("/api/training", {
      dataset,
      timeframe,
      instrument: instrumento,
      train_end: trainEnd || null,
      max_units: maxUnits ? Number(maxUnits) : undefined,
      activate: activar,
      ...form,
    });
    if (!r.ok) push(r.error ?? "No se pudo lanzar el entrenamiento.", "danger");
    else {
      push("Entrenamiento lanzado.");
      setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
    }
  };

  const descargar = async () => {
    const r = await postJSON<{ ok: boolean; error?: string }>("/api/training/download", {
      symbol: instrumento,
      timeframe,
      years,
    });
    if (!r.ok) push(r.error ?? "No se pudo lanzar la descarga.", "danger");
    else {
      push("Descarga lanzada.");
      setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
    }
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
  const desajuste =
    !!dataset &&
    !!instrumento &&
    !dataset.startsWith(`${slug(instrumento)}_${timeframe.toLowerCase()}_`);
  const curva = useMemo(() => job?.curve ?? [], [job]);
  const bateReferencia =
    job?.test_metrics?.crr != null &&
    job?.benchmark_metrics?.crr != null &&
    job.test_metrics.crr > job.benchmark_metrics.crr &&
    (job.test_metrics.sharpe ?? -1) > 0;

  const progreso = Math.round((job?.progress ?? 0) * 100);
  const faena =
    job?.kind === "precompute"
      ? "Precalculando la señal FSR"
      : job?.kind === "download"
        ? "Descargando histórico"
        : "Entrenando";

  return (
    <div className="stack">
      {/* ---------------- en curso ---------------- */}
      {corriendo && (
        <Panel
          label={faena}
          actions={
            <Mark tone="info" dot live>
              {progreso}%
            </Mark>
          }
          caption={job?.note}
        >
          <div role="status" aria-live="polite">
            <div
              className="meter"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progreso}
              aria-label={faena}
            >
              <span style={{ "--fill": progreso / 100 } as React.CSSProperties} />
            </div>
          </div>
          {curva.length > 1 && (
            <div style={{ display: "grid", gap: "var(--s-5)", marginTop: "var(--s-5)" }}>
              <Curve points={curva} pick={(p) => p.mean_reward} tone="long" label="Recompensa media por episodio" />
              <Curve points={curva} pick={(p) => p.entropy} tone="accent" label="Entropía de la política (exploración)" />
            </div>
          )}
        </Panel>
      )}

      {job?.status === "error" && (
        <Notice tone="danger" title="El último trabajo falló.">
          {job.error}
        </Notice>
      )}

      <div className="stack">
        {/* ---------------- histórico ---------------- */}
        <Panel
          label="Histórico"
          actions={
            <button className="btn" onClick={descargar} disabled={corriendo || !instrumento}>
              {corriendo ? "Hay un trabajo en curso" : "Descargar"}
            </button>
          }
          caption={
            <>
              Va por la sesión FXCM que el bot ya tiene abierta: no abre un segundo login ni cambia
              el instrumento que opera. El archivo queda en <code>data/history/</code> y se
              selecciona solo al terminar; es el mismo resultado que{" "}
              <code>scripts/download_history.py</code>. Bajar años de M15 o M30 tarda bastante más
              que de H4 o D1, y mientras tanto no se puede lanzar un entrenamiento.
            </>
          }
        >
          <div className="field-grid">
            <div className="field">
              <label className="field-label" htmlFor="instrumento">
                Instrumento
              </label>
              <select
                id="instrumento"
                className="select"
                value={instrumento}
                onChange={(e) => setInstrumento(e.target.value)}
              >
                {!instrumentos.some((i) => i.symbol === instrumento) && instrumento && (
                  <option value={instrumento}>{instrumento}</option>
                )}
                {instrumentos.map((i) => (
                  <option key={i.symbol} value={i.symbol}>
                    {i.symbol}
                  </option>
                ))}
              </select>
              <span className="field-note">El modelo queda ligado a este símbolo.</span>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="timeframe">
                Temporalidad
              </label>
              <select
                id="timeframe"
                className="select"
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
              >
                {["m15", "m30", "h1", "h4", "d1"].map((t) => (
                  <option key={t} value={t}>
                    {t.toUpperCase()}
                  </option>
                ))}
              </select>
              <span className="field-note">Y también a este reloj.</span>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="years">
                Años de histórico
              </label>
              <input
                id="years"
                className="input"
                type="number"
                min={1}
                max={10}
                step={1}
                value={years}
                onChange={(e) => setYears(Number(e.target.value))}
              />
              <span className="field-note">Entre 1 y 10.</span>
            </div>
          </div>
        </Panel>

        {/* ---------------- resultado de descarga ---------------- */}
        {job?.status === "done" && job.kind === "download" && (
          <Panel label="Histórico descargado" actions={<Mark tone="ok">{job.elapsed_s}s</Mark>}>
            <p>
              <strong>{job.dataset}</strong> — {job.bars?.toLocaleString("es")} velas de{" "}
              {job.symbol} {job.timeframe?.toUpperCase()}, de {job.first_bar?.slice(0, 10)} a{" "}
              {job.last_bar?.slice(0, 10)}. Ya está seleccionado como histórico del entrenamiento.
            </p>
          </Panel>
        )}
      </div>

      {/* ---------------- entrenamiento ---------------- */}
      <Panel
        label="Nuevo entrenamiento"
        actions={
          <button
            className="btn primary"
            onClick={lanzar}
            disabled={corriendo || !dataset || desajuste}
          >
            {corriendo ? "Hay un trabajo en curso" : "Entrenar"}
          </button>
        }
        caption={
          <>
            El tramo de test no interviene en el entrenamiento: solo se mide al final. Si las
            características FSR de este histórico no están cacheadas, se calculan primero y eso
            tarda bastante.
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--s-5)" }}>
          <Notice tone="info">
            Se entrenará <strong>{instrumento || "—"}</strong> en{" "}
            <strong>{timeframe.toUpperCase()}</strong>, según lo elegido arriba.
          </Notice>

          {desajuste && (
            <Notice tone="danger" title="El histórico no corresponde al instrumento.">
              <strong>{dataset}</strong> no es{" "}
              <strong>
                {instrumento} {timeframe.toUpperCase()}
              </strong>
              . El backend no permite etiquetar un modelo con precios de otro instrumento o reloj:
              descarga el histórico correcto arriba.
            </Notice>
          )}

          {datasets.length === 0 && (
            <Notice tone="warn" title="No hay ningún histórico descargado.">
              Bájalo con el panel de arriba, o desde la línea de órdenes con{" "}
              <code>
                uv run python scripts/download_history.py --symbols {instrumento || "EUR/USD"}{" "}
                --timeframes {timeframe} --years 3
              </code>
              .
            </Notice>
          )}

          <div className="field-grid">
            <div className="field">
              <label className="field-label" htmlFor="dataset">
                Histórico
              </label>
              <select
                id="dataset"
                className="select"
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
              >
                {datasets.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="train-end">
                Fin del tramo de train
              </label>
              <input
                id="train-end"
                className="input"
                type="date"
                value={trainEnd}
                onChange={(e) => setTrainEnd(e.target.value)}
              />
              <span className="field-note">Vacío = el 75% inicial del histórico.</span>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="max-units">
                Exposición máxima (uds, opcional)
              </label>
              <input
                id="max-units"
                className="input"
                type="number"
                min={0}
                step={1}
                placeholder="automático"
                value={maxUnits}
                onChange={(e) => setMaxUnits(e.target.value)}
              />
              <span className="field-note">
                Vacío = automático según el instrumento (~2:1 sobre capital). Un valor fijo
                aplicado a un instrumento de precio alto —oro, índices— puede sobreexponer la
                cuenta por miles de veces y producir un modelo que nunca opera.
              </span>
            </div>
          </div>

          {GRUPOS.map((grupo) => (
            <fieldset key={grupo.title} style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="field-label" style={{ marginBottom: "var(--s-1)" }}>
                {grupo.title}
              </legend>
              <p className="field-note" style={{ marginBottom: "var(--s-3)" }}>
                {grupo.caption}
              </p>
              <div className="field-grid">
                {grupo.fields.map((c) => (
                  <div className="field" key={c.key}>
                    <label className="field-label" htmlFor={c.key}>
                      {c.label}
                    </label>
                    <input
                      id={c.key}
                      className="input"
                      type="number"
                      min={c.min}
                      max={c.max}
                      step={c.step}
                      value={form[c.key]}
                      onChange={(e) => setForm({ ...form, [c.key]: Number(e.target.value) })}
                    />
                    <span className="field-note">{c.note}</span>
                  </div>
                ))}
              </div>
            </fieldset>
          ))}

          <label style={{ display: "flex", alignItems: "center", gap: "var(--s-2)" }}>
            <input
              type="checkbox"
              checked={activar}
              onChange={(e) => setActivar(e.target.checked)}
              style={{ width: 15, height: 15, accentColor: "var(--accent)" }}
            />
            <span>Activar este modelo al terminar, si el run acaba bien</span>
          </label>
        </div>
      </Panel>

      {/* ---------------- resultado ---------------- */}
      {job?.status === "done" && job.kind === "training" && (
        <Panel
          label={`Resultado — ${job.run_id}`}
          actions={<Mark tone={bateReferencia ? "ok" : "warn"}>{job.elapsed_s}s</Mark>}
          bleed
          caption={
            bateReferencia
              ? "Este run bate a comprar-y-mantener con Sharpe positivo fuera de muestra. Un solo run no es evidencia: repite con varias semillas antes de activarlo."
              : "Este run NO supera a comprar-y-mantener fuera de muestra. Comparar train contra test indica si es falta de aprendizaje o sobreajuste."
          }
        >
          <TableFrame>
            <table>
              <MetricsHead />
              <tbody>
                <MetricsRow name="Buy &amp; Hold (test)" metrics={job.benchmark_metrics} />
                <MetricsRow
                  name="FSRPPO (test)"
                  metrics={job.test_metrics}
                  reference={job.benchmark_metrics}
                  highlight
                />
                <MetricsRow name="FSRPPO (train)" metrics={job.train_metrics} />
              </tbody>
            </table>
          </TableFrame>
          {(job.curve?.length ?? 0) > 1 && (
            <div style={{ display: "grid", gap: "var(--s-5)", padding: "var(--s-4)" }}>
              <Curve points={job.curve!} pick={(p) => p.mean_reward} tone="long" label="Recompensa media por episodio" />
              <Curve points={job.curve!} pick={(p) => p.value_loss} tone="warn" label="Pérdida de la red de valor" />
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
