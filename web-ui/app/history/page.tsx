"use client";
/* Historial de operaciones cerradas + estadísticas acumuladas. */

import { useEffect, useMemo, useState } from "react";
import AssetBadge from "@/components/ui/AssetBadge";
import EmptyState from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import Readout, { ReadoutRow } from "@/components/ui/Readout";
import Skeleton from "@/components/ui/Skeleton";
import { SortHeader, TableFrame, useSort } from "@/components/ui/Table";
import Notice from "@/components/ui/Notice";
import { getJSON } from "@/lib/api";
import { fmt, isoShort, signedMoney, signedPips, signedUnits } from "@/lib/format";
import { formatPriceByAsset, formatVolumeByAsset, getAssetBadgeInfo, getAssetCategory } from "@/lib/instruments";
import { useLive } from "@/lib/live";
import type { Trade } from "@/lib/types";

type Column = "date" | "symbol" | "pips" | "pnl" | "units";

export default function History() {
  const { status, candleVersion } = useLive();
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [error, setError] = useState("");
  const stats = status?.stats;
  const sort = useSort<Column>("date");
  const fallbackSymbol = status?.instrument ?? "EUR/USD";
  const fallbackClass = status?.asset_class ?? "forex";
  const digits = status?.digits ?? 5;
  const lotSize = status?.lot_size ?? 100000;

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
        case "symbol":
          return t.symbol ?? fallbackSymbol;
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
  }, [trades, sort, fallbackSymbol]);

  return (
    <div className="stack">
      <ReadoutRow label="Acumulado del historial">
        <Readout label="Operaciones" value={stats?.trades ?? "—"} loading={!status} />
        <Readout
          label="P&L acumulado"
          value={signedMoney(stats?.net_pnl)}
          tone={(stats?.net_pnl ?? 0) >= 0 ? "pos" : "neg"}
          loading={!status}
          note="Resultado neto cerrado"
        />
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
          label="Pips / Puntos netos"
          value={signedPips(stats?.total_pips, " netos", 1)}
          tone={(stats?.total_pips ?? 0) >= 0 ? "pos" : "neg"}
          loading={!status}
        />
      </ReadoutRow>

      <Panel
        label="Operaciones cerradas"
        count={ordenadas.length}
        bleed
        caption="Historial de operaciones con signo de orden (+ Compra / − Venta), clasificación por tipo de activo (Divisas, Acciones, CFD) y desglose de precio y resultado."
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
            hint="Cuando se cierre la primera operación aparecerá aquí con su signo, su instrumento, sus pips/puntos, su P&L y el motivo del cierre."
          />
        ) : (
          <TableFrame>
            <table>
              <thead>
                <tr>
                  <th>Operación</th>
                  <SortHeader column="symbol" sort={sort}>
                    Instrumento
                  </SortHeader>
                  <SortHeader column="units" sort={sort} numeric>
                    Posición / Volumen
                  </SortHeader>
                  <th className="num">Entrada</th>
                  <th className="num">Salida</th>
                  <SortHeader column="pips" sort={sort} numeric>
                    Pips / Puntos
                  </SortHeader>
                  <SortHeader column="pnl" sort={sort} numeric>
                    P&L Neto
                  </SortHeader>
                  <th>Motivo</th>
                  <SortHeader column="date" sort={sort}>
                    Cierre
                  </SortHeader>
                </tr>
              </thead>
              <tbody>
                {ordenadas.map((t, i) => {
                  const sym = t.symbol || fallbackSymbol;
                  const cls = t.asset_class || fallbackClass;
                  const cat = getAssetCategory(sym, cls);
                  const isLong = t.side === "long";
                  const unitSuffix =
                    cat === "forex" && lotSize >= 100000
                      ? ` (${signedUnits(t.units / lotSize, t.side, 2)} lotes)`
                      : "";

                  return (
                    <tr key={t.id ?? t.trade_id ?? i}>
                      <td>
                        <span
                          className={`mark ${isLong ? "ok" : "danger"}`}
                          style={{
                            fontWeight: 700,
                            letterSpacing: "0.04em",
                          }}
                        >
                          <span className="dot" />
                          {isLong ? "+ COMPRA ▲" : "− VENTA ▼"}
                        </span>
                      </td>
                      <td>
                        <AssetBadge symbol={sym} assetClass={cls} size="sm" showType={true} />
                      </td>
                      <td className={`num ${isLong ? "pos" : "neg"}`}>
                        <strong>{signedUnits(t.units, t.side, 0)}</strong>
                        <span style={{ fontSize: "var(--fs-2xs)", color: "var(--ink-3)", marginLeft: "var(--s-1)" }}>
                          {cat === "share" ? "acc" : cat.startsWith("cfd_") ? "contr" : "uds"}
                          {unitSuffix}
                        </span>
                      </td>
                      <td className="num">{formatPriceByAsset(t.entry_rate ?? t.entry, sym, cls, digits)}</td>
                      <td className="num">{formatPriceByAsset(t.exit_rate ?? t.exit, sym, cls, digits)}</td>
                      <td className={`num ${(t.pips ?? 0) >= 0 ? "pos" : "neg"}`}>
                        {t.pips == null
                          ? "—"
                          : signedPips(
                              t.pips,
                              cat === "share" ? " pts" : cat.startsWith("cfd_") ? " pts" : " pips",
                              1
                            )}
                      </td>
                      <td
                        className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}
                        style={{ fontWeight: 700 }}
                      >
                        {t.pnl == null ? "—" : signedMoney(t.pnl)}
                      </td>
                      <td>
                        <span
                          style={{
                            display: "inline-block",
                            padding: "1px 6px",
                            fontSize: "var(--fs-eje)",
                            fontWeight: 600,
                            letterSpacing: "0.04em",
                            textTransform: "uppercase",
                            background: "var(--panel-inset)",
                            border: "1px solid var(--rule-faint)",
                            color: "var(--ink-2)",
                          }}
                        >
                          {t.reason ? t.reason.toUpperCase() : "CIERRE"}
                        </span>
                      </td>
                      <td>{isoShort(t.exit_time ?? t.entry_time)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>
    </div>
  );
}
