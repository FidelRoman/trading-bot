"use client";
/* EL MANDATO — qué opera el bot, en un solo bloque.

   Antes esto estaba repartido: el instrumento en una tarjeta, la estrategia
   activa en otra tarjeta sin título del lateral, y la dependencia de FSRPPO
   respecto a un modelo entrenado no se veía por ninguna parte, aunque sin
   modelo el bot sencillamente no opera. Las tres cosas responden a la misma
   pregunta, así que se leen juntas y en orden de causa. */

import { useId, useState } from "react";
import Link from "next/link";
import InstrumentPicker from "./InstrumentPicker";
import Mark from "./ui/Mark";
import Notice from "./ui/Notice";
import { Panel } from "./ui/Panel";
import { useToast } from "./ui/Toast";
import { postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

const STRATEGIES = [
  { key: "fsrppo", label: "FSRPPO — posición neta", needsModel: true },
  { key: "bollinger", label: "Reversión Bollinger", needsModel: false },
  { key: "rsi", label: "Estrategia RSI", needsModel: false },
  { key: "wyckoff_1", label: "Método Wyckoff 1", needsModel: false },
];

export default function Mandate() {
  const { status, refreshStatus } = useLive();
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const strategyId = useId();

  const active = status?.active_strategy || "bollinger";
  const strategy = STRATEGIES.find((s) => s.key === active);
  const symbol = status?.instrument ?? "—";
  const model = status?.active_model;
  const timeframe = (status?.timeframe ?? "—").toUpperCase();
  const modelRules = status?.timeframe_source === "modelo";

  async function change(next: string) {
    setBusy(true);
    try {
      const result = await postJSON<{ ok: boolean; error?: string }>("/api/settings", {
        active_strategy: next,
      });
      if (!result.ok) throw new Error(result.error ?? "No se pudo actualizar la estrategia.");
      await refreshStatus();
      push("Estrategia actualizada.");
    } catch (cause) {
      push(
        cause instanceof Error ? cause.message : "No se pudo actualizar la estrategia.",
        "danger"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      label="Mandato"
      caption={
        <>
          El bot decide una vez por cada vela cerrada de <strong>{timeframe}</strong>
          {modelRules
            ? ", que fija el modelo activo y no los ajustes."
            : ", según la temporalidad de los ajustes."}{" "}
          El agente propone y el control de riesgo veta: spread, sesión, límite de operaciones y
          límite de pérdida diaria pueden anular la decisión.
        </>
      }
    >
      {/* Es lo que el motor ejecuta: al apuntar a «Detener bot» se resalta. */}
      <div style={{ display: "grid", gap: "var(--s-4)" }} data-reach-target="engine">
        <InstrumentPicker />

        <div className="field">
          <label className="field-label" htmlFor={strategyId}>
            Estrategia
          </label>
          <select
            id={strategyId}
            className="select"
            value={active}
            disabled={busy}
            onChange={(event) => change(event.target.value)}
          >
            {STRATEGIES.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="field-note">
            Sus parámetros se ajustan y se simulan en{" "}
            <Link href="/strategies">Estrategias</Link>.
          </span>
        </div>

        {/* La cadena FSRPPO: sin modelo activo para este símbolo, no hay operación. */}
        {strategy?.needsModel && (
          <div className="field">
            <span className="field-label">Modelo para {symbol}</span>
            {model ? (
              <>
                <span>
                  <Mark tone="ok" dot>
                    {model}
                  </Mark>
                </span>
                <span className="field-note">
                  Entrenado en {status?.active_model_instrument}{" "}
                  {status?.active_model_timeframe?.toUpperCase()}.{" "}
                  <Link href="/models">Ver modelos</Link>
                </span>
              </>
            ) : (
              <Notice tone="warn" title={`Sin modelo activo para ${symbol}.`}>
                FSRPPO no operará este instrumento. Cada instrumento tiene su propio modelo,
                porque el tamaño de las órdenes se calcula con la ficha del activo con el que se
                entrenó. <Link href="/models">Elige uno</Link> o{" "}
                <Link href="/train">entrena uno nuevo</Link>.
              </Notice>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
