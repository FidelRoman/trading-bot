"use client";

import { useEffect, useRef, useState } from "react";
import { getJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { LogLine } from "@/lib/types";

export default function LogsPanel({ grow, limit = 120 }: { grow?: boolean; limit?: number }) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const { logVersion } = useLive();
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJSON<LogLine[]>(`/api/logs?limit=${limit}`).then((l) => alive && setLogs(l)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [logVersion, limit]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div ref={feedRef} className={`log-feed${grow ? " grow" : ""}`}>
      {logs.map((l, i) => (
        <div key={i}>
          <span className="log-ts">[{l.ts.slice(11, 19)}]</span>
          <span className={`log-${l.level}`}>{l.message}</span>
        </div>
      ))}
    </div>
  );
}
