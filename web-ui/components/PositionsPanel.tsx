"use client";

import { fmt, fmtPx, sign } from "@/lib/format";
import { postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function PositionsPanel({ onAction }: { onAction?: (msg: string, ok: boolean) => void }) {
  const { positions, prices, status } = useLive();
  const digits = status?.digits ?? 5;
  const lotSize = status?.lot_size ?? 100000;
  const symbol = status?.instrument ?? "—";

  async function closeOne(tradeId: string) {
    if (!confirm("¿Cerrar esta posición a mercado?")) return;
    const r = await postJSON(`/api/close/${tradeId}`);
    onAction?.(r.ok ? "Cierre enviado" : `Error: ${r.error}`, !!r.ok);
  }

  async function closeAll() {
    if (!confirm("¿Cerrar TODAS las posiciones abiertas a mercado?")) return;
    const r = await postJSON<{ ok: boolean; error?: string }>("/api/close-all");
    onAction?.(r.ok ? "Cierre total en cola" : `Error: ${r.error}`, !!r.ok);
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">ACTIVE POSITIONS ({positions.length})</div>
        <button className="link-btn danger" onClick={closeAll}>CLOSE ALL</button>
      </div>
      {positions.length === 0 && <div className="empty">Sin posiciones abiertas</div>}
      {positions.map((p) => {
        const pl = p.gross_pl ?? 0;
        const barW = Math.min((Math.abs(pl) / 100) * 100, 100);
        return (
          <div className="pos-card" key={p.trade_id}>
            <div className="pos-top">
              <span className={`badge ${p.side === "long" ? "badge-buy" : "badge-sell"}`}>
                {p.side === "long" ? "BUY" : "SELL"}
              </span>
              <span className="pos-pair">{symbol}</span>
              <span className={`pos-pl ${pl >= 0 ? "pos" : "neg"}`}>{sign(pl)}</span>
              <button className="pos-close" title="Cerrar posición" onClick={() => closeOne(p.trade_id)}>
                ✕
              </button>
            </div>
            <div className="pos-mid">
              {/* 1 lote son 100.000 unidades solo en divisas; en acciones y
                  metales el lote lo define el bróker, así que se ven unidades. */}
              {lotSize >= 100000
                ? <span>Vol: <b>{fmt(p.units / lotSize, 2)}</b></span>
                : <span>Uds: <b>{fmt(p.units, 0)}</b></span>}
              <span>Open: <b>{fmtPx(p.open_rate, digits)}</b></span>
              <span>Cur: <b>{fmtPx(prices?.bid, digits)}</b></span>
            </div>
            <div className="pos-bar">
              <div
                className="fill"
                style={{ width: `${barW}%`, background: pl >= 0 ? "#4ade80" : "#f0716a" }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
