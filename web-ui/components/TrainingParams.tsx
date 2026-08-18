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
    <div
      style={{
        border: "1px solid var(--rule-faint)",
        background: "var(--panel)",
        padding: "var(--s-3)",
      }}
    >
      <div className="field-label" style={{ marginBottom: "var(--s-2)" }}>
        {titulo}
      </div>
      <dl style={{ display: "grid", gap: "var(--s-1)", margin: 0 }}>
        {filas.map(([etiqueta, valor, ayuda]) => (
          <div key={etiqueta} style={{ display: "flex", justifyContent: "space-between", gap: "var(--s-3)" }}>
            <dt style={{ fontSize: "var(--fs-2xs)", color: "var(--ink-3)" }} title={ayuda}>
              {etiqueta}
            </dt>
            <dd className="num" style={{ fontSize: "var(--fs-2xs)", margin: 0, fontWeight: 600 }}>
              {valor}
            </dd>
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
  const spread =
    env?.spread_pips != null ? val(env, "spread_pips") : val(instrumento, "typical_spread_pips");

  return (
    <div style={{ display: "grid", gap: "var(--s-3)" }}>
      <div
        style={{
          display: "grid",
          gap: "var(--s-3)",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        <Bloque
          titulo="Instrumento y datos"
          filas={[
            ["Instrumento", model.instrument],
            ["Temporalidad", model.timeframe?.toUpperCase() ?? "—"],
            [
              "Train",
              `${model.train_range?.[0]?.slice(0, 10) ?? "—"} → ${model.train_range?.[1]?.slice(0, 10) ?? "—"}`,
            ],
            [
              "Test",
              `${model.test_range?.[0]?.slice(0, 10) ?? "—"} → ${model.test_range?.[1]?.slice(0, 10) ?? "—"}`,
            ],
          ]}
        />
        <Bloque
          titulo="FSR · limpieza de la señal"
          filas={[
            ["Ventana", val(fsr, "window"), "Cierres que ve el agente en cada decisión"],
            ["Ensemble", val(fsr, "ensemble_size"), "Realizaciones de ruido de CEESMDAN"],
            ["Umbral Hurst", val(fsr, "hurst_threshold"), "Por debajo se descarta la capa como ruido"],
            ["δ", val(fsr, "delta"), "Criterio de parada del tamizado"],
          ]}
        />
        <Bloque
          titulo="PPO · aprendizaje"
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
          titulo="Entorno · costes y tamaño"
          filas={[
            ["Spread asumido", `${spread} pips`, "El coste por operar: lo que hundió EUR/USD en H1"],
            ["Exposición máx.", val(env, "max_units"), "Unidades netas; depende del instrumento"],
            ["Capital inicial", val(env, "initial_equity")],
            ["Importe por op.", `${val(env, "min_trade_amount")} – ${val(env, "max_trade_amount")}`],
          ]}
        />
      </div>
      <details>
        <summary className="field-note" style={{ cursor: "pointer" }}>
          Volcado completo
        </summary>
        <pre
          className="mono"
          style={{
            fontSize: "var(--fs-eje)",
            overflowX: "auto",
            padding: "var(--s-3)",
            border: "1px solid var(--rule-faint)",
            background: "var(--panel)",
            marginTop: "var(--s-2)",
          }}
        >
          {JSON.stringify(
            { fsr: model.fsr_params, ppo: model.ppo_params, env: model.env_params },
            null,
            2
          )}
        </pre>
      </details>
    </div>
  );
}
