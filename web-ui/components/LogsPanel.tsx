"use client";

import { useEffect, useRef, useState } from "react";
import { getJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { LogLine } from "@/lib/types";

export default function LogsPanel({ grow, limit = 120 }: { grow?: boolean; limit?: number }) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [error, setError] = useState("");
  const { logVersion } = useLive();
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJSON<LogLine[]>(`/api/logs?limit=${limit}`)
        .then((lines) => { if (alive) { setLogs(lines); setError(""); } })
        .catch(() => alive && setError("No se pudo cargar el registro."));
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [logVersion, limit]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div
      ref={feedRef}
      className={`log-feed${grow ? " grow" : ""}`}
      role="log"
      aria-live="polite"
      aria-label="Registro de actividad del bot"
    >
      {error && <div className="inline-alert" role="alert">{error}</div>}
      {!error && logs.length === 0 && <div className="empty">Sin eventos recientes</div>}
      {logs.map((l, i) => (
        <div key={i}>
          <span className="log-ts">[{l.ts.slice(11, 19)}]</span>
          <span className={`log-${l.level}`}>{l.message}</span>
        </div>
      ))}
    </div>
  );
}
