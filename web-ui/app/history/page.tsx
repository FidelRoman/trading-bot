"use client";
/* Historial de operaciones cerradas + estadísticas acumuladas. */

import { useEffect, useMemo, useState } from "react";
import EmptyState from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import Readout, { ReadoutRow } from "@/components/ui/Readout";
import Skeleton from "@/components/ui/Skeleton";
import { SortHeader, TableFrame, useSort } from "@/components/ui/Table";
import Notice from "@/components/ui/Notice";
import { getJSON } from "@/lib/api";
import { fmt, fmtPx, isoShort, sign } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { Trade } from "@/lib/types";

type Column = "date" | "pips" | "pnl" | "units";

export default function History() {
  const { status, candleVersion } = useLive();
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [error, setError] = useState("");
  const stats = status?.stats;
  const sort = useSort<Column>("date");

  useEffect(() => {
    getJSON<Trade[]>("/api/trades?limit=200")
      .then((rows) => {
        setTrades(rows);
        setError("");
      })
      .catch(() => {
        setTrades([]);
        setError("No se pudo cargar el historial de operaciones.");
      });
  }, [candleVersion]);

  const ordenadas = useMemo(() => {
    const rows = [...(trades ?? [])];
    const value = (t: Trade): number | string | null | undefined => {
      switch (sort.key) {
        case "pips":
          return t.pips;
        case "pnl":
          return t.pnl;
        case "units":
          return t.units;
        default:
          return t.exit_time ?? t.entry_time;
      }
    };
    return rows.sort((a, b) => sort.compare(value(a), value(b)));
  }, [trades, sort]);

  return (
    <div className="stack">
      <ReadoutRow label="Acumulado del historial">
        <Readout label="Operaciones" value={stats?.trades ?? "—"} loading={!status} />
        <Readout
          label="Tasa de acierto"
          value={`${fmt(stats?.win_rate_pct, 1)}%`}
          loading={!status}
          note="Sobre las cerradas"
        />
        <Readout
          label="Profit factor"
          value={stats?.profit_factor == null ? "—" : fmt(stats.profit_factor)}
          loading={!status}
          note="Ganado entre perdido"
        />
        <Readout
          label="Pips netos"
          value={fmt(stats?.total_pips, 1)}
          tone={(stats?.total_pips ?? 0) >= 0 ? "pos" : "neg"}
          loading={!status}
        />
      </ReadoutRow>

      <Panel
        label="Operaciones cerradas"
        count={ordenadas.length}
        bleed
        caption="Las últimas 200 operaciones que el bot o una orden manual llevaron hasta el cierre, con el motivo por el que se cerraron."
      >
        {error && (
          <div style={{ padding: "var(--s-4)" }}>
            <Notice tone="danger">{error}</Notice>
          </div>
        )}
        {trades === null ? (
          <div style={{ padding: "var(--s-4)" }}>
            <Skeleton height={24} count={5} />
          </div>
        ) : ordenadas.length === 0 && !error ? (
          <EmptyState
            title="Sin operaciones todavía"
            hint="Cuando se cierre la primera operación aparecerá aquí con sus pips, su P&L y el motivo del cierre."
          />
        ) : (
          <TableFrame>
            <table>
              <thead>
                <tr>
                  <th>Dirección</th>
                  <SortHeader column="units" sort={sort} numeric>
                    Unidades
                  </SortHeader>
                  <th className="num">Entrada</th>
                  <th className="num">Salida</th>
                  <SortHeader column="pips" sort={sort} numeric>
                    Pips
                  </SortHeader>
                  <SortHeader column="pnl" sort={sort} numeric>
                    P&L
                  </SortHeader>
                  <th>Motivo</th>
                  <SortHeader column="date" sort={sort}>
                    Fecha
                  </SortHeader>
                </tr>
              </thead>
              <tbody>
                {ordenadas.map((t, i) => (
                  <tr key={t.id ?? i}>
                    <td className={t.side === "long" ? "pos" : "neg"}>
                      {t.side === "long" ? "Compra" : "Venta"}
                    </td>
                    <td className="num">{fmt(t.units, 0)}</td>
                    <td className="num">{fmtPx(t.entry_rate)}</td>
                    <td className="num">{fmtPx(t.exit_rate)}</td>
                    <td className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                      {t.pips == null ? "—" : fmt(t.pips, 1)}
                    </td>
                    <td className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                      {t.pnl == null ? "—" : sign(t.pnl)}
                    </td>
                    <td>{t.reason ?? "—"}</td>
                    <td>{isoShort(t.exit_time ?? t.entry_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>
    </div>
  );
}
