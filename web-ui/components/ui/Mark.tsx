"use client";
/* Marca de estado: una sola familia para modo de cuenta, conexión y motor.
   Antes había cuatro indicadores con cuatro vocabularios distintos. */

import type React from "react";

export default function Mark({
  tone = "neutral",
  dot,
  live,
  children,
}: {
  tone?: "neutral" | "ok" | "warn" | "danger" | "info";
  dot?: boolean;
  /** Punto latiendo: solo para lo que está ocurriendo ahora mismo. */
  live?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className={`mark${tone === "neutral" ? "" : ` ${tone}`}${live ? " live" : ""}`}>
      {(dot || live) && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
