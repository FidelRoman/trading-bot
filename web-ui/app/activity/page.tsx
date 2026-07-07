"use client";
/* Monitor de actividad: curva de equity real + registro completo del bot. */

import { useEffect, useState } from "react";
import { AreaChart } from "@/components/charts";
import LogsPanel from "@/components/LogsPanel";
import { getJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function Activity() {
  const { candleVersion } = useLive();
  const [equity, setEquity] = useState<{ time: number; value: number }[]>([]);

  useEffect(() => {
    getJSON<{ ts: string; equity: number }[]>("/api/equity")
      .then((rows) => {
        const seen = new Set<number>();
        const data: { time: number; value: number }[] = [];
        for (const r of rows) {
          const t = Math.floor(new Date(r.ts).getTime() / 1000);
          if (!seen.has(t)) { seen.add(t); data.push({ time: t, value: r.equity }); }
        }
        setEquity(data);
      })
      .catch(() => {});
  }, [candleVersion]);

  return (
    <>
      <div className="card mb">
        <div className="card-head"><div className="card-title">∿ EQUITY CURVE</div></div>
        <AreaChart data={equity} />
      </div>
      <div className="card">
        <div className="card-head"><div className="card-title">▤ ACTIVITY MONITOR</div></div>
        <LogsPanel grow />
      </div>
    </>
  );
}
