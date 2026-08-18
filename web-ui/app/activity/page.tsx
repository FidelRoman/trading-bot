"use client";
/* Monitor de actividad: curva de capital real + registro completo del bot. */

import { useEffect, useState } from "react";
import { AreaChart } from "@/components/charts";
import LogsPanel from "@/components/LogsPanel";
import EmptyState from "@/components/ui/EmptyState";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import Skeleton from "@/components/ui/Skeleton";
import { getJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function Activity() {
  const { candleVersion } = useLive();
  const [equity, setEquity] = useState<{ time: number; value: number }[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJSON<{ ts: string; equity: number }[]>("/api/equity")
      .then((rows) => {
        const seen = new Set<number>();
        const data: { time: number; value: number }[] = [];
        for (const r of rows) {
          const t = Math.floor(new Date(r.ts).getTime() / 1000);
          if (!seen.has(t)) {
            seen.add(t);
            data.push({ time: t, value: r.equity });
          }
        }
        setEquity(data);
      })
      .catch(() => {
        setEquity([]);
        setError("No se pudo cargar la curva de capital.");
      });
  }, [candleVersion]);

  const first = equity?.[0]?.value;
  const last = equity?.[equity.length - 1]?.value;
  const up = first != null && last != null ? last >= first : true;

  return (
    <div className="stack">
      <Panel
        label="Curva de capital"
        bleed
        caption="El capital real de la cuenta, anotado en cada actualización de estado. No es una simulación: es lo que ha pasado."
      >
        <div style={{ padding: "var(--s-3) var(--s-2)" }}>
          {error ? (
            <Notice tone="danger">{error}</Notice>
          ) : equity === null ? (
            <Skeleton height={240} />
          ) : equity.length === 0 ? (
            <EmptyState
              title="Sin capital registrado todavía"
              hint="La curva empieza a dibujarse en cuanto el bot recibe el primer estado de cuenta del bróker."
            />
          ) : (
            <AreaChart
              data={equity}
              tone={up ? "long" : "short"}
              fit
              label="Curva de capital de la cuenta"
            />
          )}
        </div>
      </Panel>

      <Panel
        label="Monitor de actividad"
        caption="Cada decisión del agente, cada veto del control de riesgo y cada orden quedan anotadas aquí en el momento en que ocurren."
      >
        <LogsPanel grow />
      </Panel>
    </div>
  );
}
