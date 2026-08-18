"use client";
/* Qué decidió el agente en la última barra cerrada, y con qué señal.
   La dependencia del modelo se lee en el Mandato; aquí va la decisión. */

import Link from "next/link";
import Notice from "./ui/Notice";
import { Panel } from "./ui/Panel";
import Readout from "./ui/Readout";
import { useLive } from "@/lib/live";
import { fmt, fmtPx } from "@/lib/format";

const SIDES: Record<string, { text: string; tone: "pos" | "neg" | "none" }> = {
  buy: { text: "Aumentar largo", tone: "pos" },
  sell: { text: "Aumentar corto", tone: "neg" },
  hold: { text: "Mantener", tone: "none" },
};

export default function FsrppoPanel() {
  const { status } = useLive();
  if (status?.active_strategy !== "fsrppo" || !status?.active_model) return null;

  const decision = status?.last_decision ?? null;
  const info = status?.active_model_info ?? null;
  const net = status?.net_position ?? 0;
  const side = decision ? (SIDES[decision.side] ?? SIDES.hold) : null;
  const kept = decision?.kept.filter(Boolean).length ?? 0;

  return (
    <Panel
      label="Decisión del agente"
      caption={
        decision ? (
          <>
            Acción (a₁, a₂) = ({decision.action[0]?.toFixed(3)}, {decision.action[1]?.toFixed(3)}).
            Hurst por modo:{" "}
            {decision.hursts.map((h, i) => (
              <span key={i} className={decision.kept[i] ? "pos" : "neg"}>
                {h.toFixed(2)}
                {i < decision.hursts.length - 1 ? " · " : ""}
              </span>
            ))}
            . Se descartó el {(decision.discarded_energy * 100).toFixed(1)}% de la varianza como
            ruido de alta frecuencia. <Link href="/fsr">Ver la descomposición</Link>.
          </>
        ) : (
          <>
            Todavía no hay ninguna barra cerrada desde que este modelo está activo. La primera
            decisión aparecerá al cierre de la siguiente vela.
          </>
        )
      }
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: "var(--s-4)",
        }}
      >
        <Readout
          label="Posición neta"
          value={net === 0 ? "Plana" : fmt(net, 0)}
          tone={net > 0 ? "pos" : net < 0 ? "neg" : "none"}
        />
        <Readout label="Última decisión" value={side?.text ?? "—"} tone={side?.tone} />
        <Readout
          label="Objetivo / precio"
          value={decision ? `${fmt(decision.target_position, 0)} @ ${fmtPx(decision.price)}` : "—"}
        />
        <Readout
          label="Modos conservados"
          value={decision ? `${kept} de ${decision.kept.length}` : "—"}
          note="Los de memoria larga (H > 0,5)"
        />
      </div>

      {info?.meets_acceptance === false && (
        <div style={{ marginTop: "var(--s-4)" }}>
          <Notice tone="warn" title="Modelo no validado.">
            Sigue operativo por decisión del operador, pero sus métricas no cumplen Sharpe &gt; 0 y
            CRR &gt; Buy &amp; Hold fuera de muestra.
          </Notice>
        </div>
      )}
    </Panel>
  );
}
