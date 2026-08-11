"use client";
/* Hiperparámetros de un modelo entrenado, legibles.

   Antes se volcaban con JSON.stringify: técnicamente completo e inservible para
   comparar dos modelos de un vistazo. Aquí salen los que de verdad cambian el
   resultado, agrupados por etapa, y el volcado completo queda debajo por si hace
   falta el detalle. */

import type { ModelRecord } from "@/lib/types";

/** Lee una clave admitiendo que falte, y la formatea sin inventar ceros. */
function val(source: Record<string, unknown>, key: string): string {
  const raw = source?.[key];
  if (raw == null) return "—";
  if (Array.isArray(raw)) return raw.join(" × ");
  if (typeof raw === "number") {
    // Los learning rate salen en notación científica; el resto, tal cual.
    return Math.abs(raw) < 0.001 && raw !== 0 ? raw.toExponential(1) : String(raw);
  }
  if (typeof raw === "boolean") return raw ? "sí" : "no";
  if (typeof raw === "object") return "—";
  return String(raw);
}

function Bloque({ titulo, filas }: { titulo: string; filas: [string, string, string?][] }) {
  return (
    <div className="param-block">
      <div className="param-block-title">{titulo}</div>
      <dl className="param-grid">
        {filas.map(([etiqueta, valor, ayuda]) => (
          <div key={etiqueta} className="param-item">
            <dt title={ayuda}>{etiqueta}</dt>
            <dd>{valor}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function TrainingParams({ model }: { model: ModelRecord }) {
  const fsr = model.fsr_params as Record<string, unknown>;
  const ppo = model.ppo_params as Record<string, unknown>;
  const env = model.env_params as Record<string, unknown>;
  // El spread puede venir explícito o heredado de la ficha del instrumento.
  const instrumento = (env?.instrument ?? {}) as Record<string, unknown>;
  const spread = env?.spread_pips != null
    ? val(env, "spread_pips")
    : val(instrumento, "typical_spread_pips");

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className="param-blocks">
        <Bloque
          titulo="INSTRUMENTO Y DATOS"
          filas={[
            ["Instrumento", model.instrument],
            ["Timeframe", model.timeframe?.toUpperCase() ?? "—"],
            ["Train", `${model.train_range?.[0]?.slice(0, 10) ?? "—"} → ${model.train_range?.[1]?.slice(0, 10) ?? "—"}`],
            ["Test", `${model.test_range?.[0]?.slice(0, 10) ?? "—"} → ${model.test_range?.[1]?.slice(0, 10) ?? "—"}`],
          ]}
        />
        <Bloque
          titulo="FSR · LIMPIEZA DE LA SEÑAL"
          filas={[
            ["Ventana", val(fsr, "window"), "Cierres que ve el agente en cada decisión"],
            ["Ensemble", val(fsr, "ensemble_size"), "Realizaciones de ruido de CEESMDAN"],
            ["Umbral Hurst", val(fsr, "hurst_threshold"), "Por debajo se descarta la capa como ruido"],
            ["δ", val(fsr, "delta"), "Criterio de parada del tamizado"],
          ]}
        />
        <Bloque
          titulo="PPO · APRENDIZAJE"
          filas={[
            ["Learning rate", val(ppo, "learning_rate"), "1e-5 es el del paper y no llega a operar en FX"],
            ["Iteraciones", val(ppo, "iterations")],
            ["Capas ocultas", val(ppo, "hidden_sizes")],
            ["γ", val(ppo, "gamma")],
            ["λ (GAE)", val(ppo, "gae_lambda")],
            ["Entropía", val(ppo, "entropy_coef")],
          ]}
        />
        <Bloque
          titulo="ENTORNO · COSTES Y TAMAÑO"
          filas={[
            ["Spread asumido", `${spread} pips`, "El coste por operar: lo que hundió EUR/USD en H1"],
            ["Exposición máx.", val(env, "max_units"), "Unidades netas; depende del instrumento"],
            ["Capital inicial", val(env, "initial_equity")],
            ["Importe por op.", `${val(env, "min_trade_amount")} – ${val(env, "max_trade_amount")}`],
          ]}
        />
      </div>
      <details>
        <summary className="hint">Volcado completo</summary>
        <pre style={{ fontSize: 11, overflowX: "auto" }}>
{JSON.stringify({ fsr: model.fsr_params, ppo: model.ppo_params, env: model.env_params }, null, 2)}
        </pre>
      </details>
    </div>
  );
}
