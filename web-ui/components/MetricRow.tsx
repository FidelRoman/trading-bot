"use client";
/* Las lecturas de cuenta, en una sola línea base bajo la banda. Están en todas
   las rutas: antes se ocultaban en tres de las ocho con una lista escrita a
   mano, y el marco de la app cambiaba sin motivo perceptible. */

import Readout, { ReadoutRow } from "./ui/Readout";
import { fmt, money, sign, signedMoney } from "@/lib/format";
import { useLive } from "@/lib/live";

export default function MetricRow() {
  const { status, floatingPl, positions } = useLive();
  const loading = !status;
  const equity = status?.account?.equity;
  const usable = status?.account?.usable_margin;
  const drawdown = status?.max_drawdown_pct ?? 0;
  
  // P&L del día considerando operaciones cerradas + órdenes abiertas flotantes
  const closedPnl = status?.daily_realized_pl ?? ((status?.daily_pl_abs ?? 0) - (status?.floating_pl ?? 0));
  const openPnl = floatingPl;
  const dayAbs = closedPnl + openPnl;
  const baseEquity = (equity != null && equity - dayAbs > 0) ? (equity - dayAbs) : (equity || 10000);
  const dayPct = baseEquity > 0 ? (dayAbs / baseEquity) * 100 : (status?.daily_pl_pct ?? 0);
  const openCount = positions.length;

  return (
    <ReadoutRow chrome>
      <Readout
        label="Capital total"
        value={money(equity)}
        loading={loading}
        note={
          loading ? undefined : (
            <span className={dayPct >= 0 ? "pos" : "neg"}>{sign(dayPct, "% hoy")}</span>
          )
        }
      />
      <Readout
        label="Margen libre"
        value={money(usable)}
        loading={loading}
        note={equity && usable != null ? `${fmt((usable / equity) * 100, 1)}% del capital` : "—"}
      />
      <Readout
        label="P&L del día"
        value={signedMoney(dayAbs)}
        tone={dayAbs > 0 ? "pos" : dayAbs < 0 ? "neg" : "none"}
        loading={loading}
        note={
          loading
            ? undefined
            : openCount > 0 || Math.abs(openPnl) > 0.001
            ? `${status?.trades_today ?? 0} cerradas (${signedMoney(closedPnl)}) · ${openCount} ${openCount === 1 ? "abierta" : "abiertas"} (${signedMoney(openPnl)})`
            : `${status?.trades_today ?? 0} de ${status?.max_trades_per_day ?? 10} operaciones hoy`
        }
      />
      <Readout
        label="Caída máxima"
        value={`${fmt(drawdown, 1)}%`}
        tone={drawdown <= -5 ? "neg" : "none"}
        loading={loading}
        note="Objetivo: por encima de −5%"
      />
    </ReadoutRow>
  );
}
