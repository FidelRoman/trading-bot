/* De qué cuenta se trata. La misma deducción vivía copiada en Sidebar, Topbar
   y StrategyControls, con tres vocabularios distintos para el mismo hecho. */

import type { Status } from "./types";

export type AccountKind = "real" | "demo" | "sim";

export interface AccountRead {
  kind: AccountKind;
  /** Etiqueta corta, la misma en toda la interfaz. */
  label: string;
  /** Lo que hace el bot con las órdenes en esta cuenta. */
  consequence: string;
  tone: "danger" | "info" | "warn";
}

export function readAccount(status: Status | null | undefined): AccountRead {
  const connection = status?.account?.connection ?? "";
  const real = Boolean(status?.live_execution && (connection === "Real" || status?.mode.includes("real")));
  const demo = Boolean(status?.live_execution && !real);

  if (real) {
    return {
      kind: "real",
      label: "Cuenta real",
      consequence: "Las órdenes salen a mercado con dinero real.",
      tone: "danger",
    };
  }
  if (demo) {
    return {
      kind: "demo",
      label: "Cuenta demo",
      consequence: "Las órdenes salen a la cuenta demo del bróker.",
      tone: "info",
    };
  }
  return {
    kind: "sim",
    label: "Simulado",
    consequence: "Nada sale al bróker: precios sintéticos y órdenes simuladas.",
    tone: "warn",
  };
}

/** Estado del motor, en las palabras que usa la banda. */
export function readEngine(status: Status | null | undefined): {
  label: string;
  tone: "ok" | "warn" | "danger" | "neutral";
  running: boolean;
} {
  if (!status) return { label: "Conectando…", tone: "neutral", running: false };
  if (status.halted_today) return { label: "Límite diario", tone: "danger", running: false };
  if (status.market_open === false && !status.connected)
    return { label: "Mercado cerrado", tone: "warn", running: false };
  if (status.paused) return { label: "Detenido", tone: "warn", running: false };
  return { label: "Operando", tone: "ok", running: true };
}
