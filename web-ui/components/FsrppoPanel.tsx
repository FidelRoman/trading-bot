"use client";
/* Estado de FSRPPO en el dashboard: qué modelo decide, qué posición neta hay
   y qué propuso el agente en la última barra cerrada. */

import Link from "next/link";
import { useLive } from "@/lib/live";
import { fmt, fmtPx } from "@/lib/format";

const LADO: Record<string, { txt: string; cls: string }> = {
  buy: { txt: "▲ AUMENTAR LARGO", cls: "dir-long" },
  sell: { txt: "▼ AUMENTAR CORTO", cls: "dir-short" },
  hold: { txt: "■ MANTENER", cls: "" },
};

export default function FsrppoPanel() {
  const { status } = useLive();
  if (status?.active_strategy !== "fsrppo") return null;

  const decision = status?.last_decision ?? null;
  const modelo = status?.active_model;
  // El modelo activo es por instrumento: al cambiar de símbolo cambia el que
  // decide, así que el panel se rotula siempre con el símbolo que opera el bot.
  const simbolo = status?.instrument ?? "—";
  const info = status?.active_model_info ?? null;
  const neta = status?.net_position ?? 0;
  const lado = decision ? LADO[decision.side] ?? LADO.hold : null;
  const conservadas = decision?.kept.filter(Boolean).length ?? 0;

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">◈ AGENTE FSRPPO</div>
        <span className={`chip${modelo ? " ok" : " warn"}`}>
          {modelo ? `${simbolo} · ${modelo}` : `SIN MODELO PARA ${simbolo}`}
        </span>
      </div>

      {!modelo ? (
        <div className="empty">
          No hay ningún modelo activo para <strong>{simbolo}</strong>: el bot no
          operará este instrumento.{" "}
          <Link href="/models" className="linkish">Elige uno</Link> o{" "}
          <Link href="/train" className="linkish">entrena uno nuevo</Link>.
          Cada instrumento tiene su propio modelo activo, porque el tamaño de las
          órdenes se calcula con la ficha del activo con el que se entrenó.
        </div>
      ) : (
        <div className="metric-row">
          <div className="metric-card">
            <div className="m-lbl">POSICIÓN NETA</div>
            <div className={`m-val ${neta > 0 ? "pos" : neta < 0 ? "neg" : ""}`}>
              {neta === 0 ? "PLANA" : fmt(neta, 0)}
            </div>
          </div>
          <div className="metric-card">
            <div className="m-lbl">ÚLTIMA DECISIÓN</div>
            <div className={`m-val ${lado?.cls ?? ""}`} style={{ fontSize: 14 }}>
              {lado?.txt ?? "—"}
            </div>
          </div>
          <div className="metric-card">
            <div className="m-lbl">OBJETIVO / PRECIO</div>
            <div className="m-val" style={{ fontSize: 14 }}>
              {decision ? `${fmt(decision.target_position, 0)} @ ${fmtPx(decision.price)}` : "—"}
            </div>
          </div>
          <div className="metric-card">
            <div className="m-lbl">MODOS CONSERVADOS</div>
            <div className="m-val">
              {decision ? `${conservadas}/${decision.kept.length}` : "—"}
            </div>
          </div>
        </div>
      )}

      {modelo && info && (
        <div className="hint" style={{ padding: "8px 12px" }}>
          Entrenado en <strong>{status?.active_model_instrument}</strong>{" "}
          {status?.active_model_timeframe?.toUpperCase()} ·
          train {info.train_range?.[0]?.slice(0, 10)} → {info.train_range?.[1]?.slice(0, 10)} ·
          test {info.test_range?.[0]?.slice(0, 10)} → {info.test_range?.[1]?.slice(0, 10)}
          {info.learning_rate != null && <> · lr {info.learning_rate}</>}
          {info.spread_pips != null && <> · spread asumido {info.spread_pips} pips</>}
          {info.max_units != null && <> · exposición máx. {fmt(info.max_units, 0)}</>}
          {" "}<Link href="/models" className="linkish">Ver parámetros</Link>
        </div>
      )}

      {decision && (
        <div className="hint" style={{ padding: "8px 12px" }}>
          Acción (a₁, a₂) = ({decision.action[0]?.toFixed(3)}, {decision.action[1]?.toFixed(3)}) ·
          Hurst por modo: {decision.hursts.map((h, i) => (
            <span key={i} className={decision.kept[i] ? "pos" : "neg"}>
              {" "}{h.toFixed(2)}
            </span>
          ))} · se descartó el {(decision.discarded_energy * 100).toFixed(1)}% de la
          varianza como ruido. <Link href="/fsr" className="linkish">Ver descomposición</Link>
        </div>
      )}
    </div>
  );
}
