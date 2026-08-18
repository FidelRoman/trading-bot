"use client";
/* El registro es lo único de la lámina compuesto en monoespaciada: son datos
   emitidos por la máquina, no prosa. */

import { useEffect, useRef, useState } from "react";
import EmptyState from "./ui/EmptyState";
import Notice from "./ui/Notice";
import Skeleton from "./ui/Skeleton";
import { getJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { LogLine } from "@/lib/types";

export default function LogsPanel({ grow, limit = 120 }: { grow?: boolean; limit?: number }) {
  const [logs, setLogs] = useState<LogLine[] | null>(null);
  const [error, setError] = useState("");
  const { logVersion } = useLive();
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJSON<LogLine[]>(`/api/logs?limit=${limit}`)
        .then((lines) => {
          if (alive) {
            setLogs(lines);
            setError("");
          }
        })
        .catch(() => alive && setError("No se pudo cargar el registro."));
    load();
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [logVersion, limit]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  if (error) return <Notice tone="danger">{error}</Notice>;
  if (logs === null)
    return (
      <div style={{ padding: "var(--s-2) 0" }}>
        <Skeleton height={13} count={6} />
      </div>
    );
  if (logs.length === 0)
    return (
      <EmptyState
        title="Sin eventos recientes"
        hint="Cada decisión, veto de riesgo y orden del bot queda anotada aquí con su hora."
      />
    );

  return (
    <div
      ref={feedRef}
      className={`log-feed${grow ? " grow" : ""}`}
      role="log"
      aria-live="polite"
      aria-label="Registro de actividad del bot"
    >
      {logs.map((line, i) => (
        <div className="log-line" key={i}>
          <span className="log-ts">{line.ts.slice(11, 19)}</span>
          <span className={`log-${line.level}`}>{line.message}</span>
        </div>
      ))}
    </div>
  );
}
