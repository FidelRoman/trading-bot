"use client";
/* Presentación de las siete métricas de la Tabla 2 del paper, compartida por
   las pestañas de entrenamiento, modelos y backtesting. */

import type { PaperMetrics } from "@/lib/types";

export const METRIC_COLUMNS: {
  key: keyof PaperMetrics;
  label: string;
  kind: "pct" | "num";
  /** true si un valor mayor es mejor; se usa para colorear. */
  higherIsBetter: boolean;
  title: string;
}[] = [
  { key: "crr", label: "CRR", kind: "pct", higherIsBetter: true, title: "Rentabilidad acumulada" },
  { key: "arr", label: "ARR", kind: "pct", higherIsBetter: true, title: "Rentabilidad anualizada" },
  { key: "avr", label: "AVR", kind: "pct", higherIsBetter: false, title: "Volatilidad anualizada" },
  { key: "max_drawdown", label: "MD", kind: "pct", higherIsBetter: false, title: "Máxima caída" },
  { key: "sharpe", label: "SHARPE", kind: "num", higherIsBetter: true, title: "Exceso de retorno por unidad de riesgo" },
  { key: "calmar", label: "CALMAR", kind: "num", higherIsBetter: true, title: "Retorno por unidad de caída" },
  { key: "sortino", label: "SORTINO", kind: "num", higherIsBetter: true, title: "Exceso de retorno por riesgo bajista" },
];

export function metricText(value: number | null | undefined, kind: "pct" | "num"): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return kind === "pct" ? `${(value * 100).toFixed(2)}%` : value.toFixed(3);
}

/** Cabecera de la tabla de métricas del paper. */
export function MetricsHead({ first = "ESTRATEGIA", extra }: { first?: string; extra?: string[] }) {
  return (
    <thead>
      <tr>
        <th>{first}</th>
        {METRIC_COLUMNS.map((c) => (
          <th key={c.key as string} title={c.title}>
            {c.label}
          </th>
        ))}
        {extra?.map((e) => <th key={e}>{e}</th>)}
      </tr>
    </thead>
  );
}

/** Fila de métricas. `reference` colorea comparando contra otra estrategia. */
export function MetricsRow({
  name,
  metrics,
  reference,
  extra,
  highlight = false,
}: {
  name: React.ReactNode;
  metrics?: PaperMetrics;
  reference?: PaperMetrics;
  extra?: React.ReactNode[];
  highlight?: boolean;
}) {
  return (
    <tr style={highlight ? { background: "rgba(74,222,128,.06)" } : undefined}>
      <td>{name}</td>
      {METRIC_COLUMNS.map((c) => {
        const value = metrics?.[c.key] as number | null | undefined;
        const base = reference?.[c.key] as number | null | undefined;
        let cls = "";
        if (
          base != null && value != null &&
          Number.isFinite(base) && Number.isFinite(value) && value !== base
        ) {
          const mejor = c.higherIsBetter ? value > base : value < base;
          cls = mejor ? "pos" : "neg";
        }
        return (
          <td key={c.key as string} className={cls}>
            {metricText(value, c.kind)}
          </td>
        );
      })}
      {extra?.map((e, i) => <td key={i}>{e}</td>)}
    </tr>
  );
}
