"use client";
/* Un solo patrón de aviso para toda la interfaz, en cuatro tonos.
   Sustituye a global-alert, inline-alert, manual-msg, bt-banner, picker-warn,
   picker-blocked y hint.ok/.err, que decían lo mismo de siete maneras. */

import type React from "react";

export type Tone = "info" | "ok" | "warn" | "danger";

export default function Notice({
  tone = "info",
  title,
  children,
  live,
}: {
  tone?: Tone;
  title?: React.ReactNode;
  children?: React.ReactNode;
  /** `alert` interrumpe al lector de pantalla; resérvalo para errores. */
  live?: "status" | "alert";
}) {
  const role = live ?? (tone === "danger" ? "alert" : "status");
  return (
    <div className={`notice ${tone}`} role={role} aria-live={role === "alert" ? "assertive" : "polite"}>
      <div>
        {title && <strong>{title}</strong>}
        {title && children ? " " : null}
        {children}
      </div>
    </div>
  );
}
