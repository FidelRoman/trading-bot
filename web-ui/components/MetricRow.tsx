"use client";
/* Las lecturas de cuenta, en una sola línea base bajo la banda. Están en todas
   las rutas: antes se ocultaban en tres de las ocho con una lista escrita a
   mano, y el marco de la app cambiaba sin motivo perceptible. */

import Readout, { ReadoutRow } from "./ui/Readout";
import { fmt, money, sign, signedMoney } from "@/lib/format";
import { useLive } from "@/lib/live";

export default function MetricRow() {
  const { status } = useLive();
  const loading = !status;
  const equity = status?.account?.equity;
  const usable = status?.account?.usable_margin;
  const dayPct = status?.daily_pl_pct ?? 0;
  const dayAbs = status?.daily_pl_abs ?? 0;
  const drawdown = status?.max_drawdown_pct ?? 0;

  return (
    <ReadoutRow chrome>
      <Readout label="Capital total" value={money(equity)} loading={loading} note={
        loading ? undefined : (
          <span className={dayPct >= 0 ? "pos" : "neg"}>{sign(dayPct, "% hoy")}</span>
        )
      } />
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
        note={status ? `${status.trades_today} de ${status.max_trades_per_day} operaciones` : "—"}
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
