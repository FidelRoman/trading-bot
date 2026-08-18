"use client";
/* Lectura de eje: rótulo pequeño arriba, valor tabular, nota debajo.
   Es la única forma de presentar una cifra en toda la lámina. */

import type React from "react";
import Skeleton from "./Skeleton";

export default function Readout({
  label,
  value,
  note,
  tone,
  size,
  loading,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  note?: React.ReactNode;
  /** El color es señal, no adorno: solo cuando el signo significa algo. */
  tone?: "pos" | "neg" | "none";
  size?: "lg";
  loading?: boolean;
}) {
  return (
    <div className={`readout${size === "lg" ? " lg" : ""}`}>
      <span className="readout-label">{label}</span>
      {loading ? (
        <Skeleton height={size === "lg" ? 26 : 20} width="5ch" />
      ) : (
        <span className={`readout-value num${tone && tone !== "none" ? ` ${tone}` : ""}`}>
          {value}
        </span>
      )}
      {note != null && <span className="readout-note">{note}</span>}
    </div>
  );
}

/** Tira de lecturas. `label` la separa de la tira de cuenta que la banda pone
 *  en todas las rutas: sin rótulo, dos tiras iguales apiladas se leen como una
 *  sola y las cifras de la página parecen continuación de las de la cuenta. */
export function ReadoutRow({
  label,
  chrome,
  children,
}: {
  label?: React.ReactNode;
  /** La tira que cuelga de la banda: chrome de la app, no dato de la página. */
  chrome?: boolean;
  children: React.ReactNode;
}) {
  if (!label) return <div className={`readout-row${chrome ? " chrome" : ""}`}>{children}</div>;
  return (
    <section className="readout-block" aria-label={typeof label === "string" ? label : undefined}>
      <span className="readout-block-label">{label}</span>
      <div className="readout-row">{children}</div>
    </section>
  );
}
