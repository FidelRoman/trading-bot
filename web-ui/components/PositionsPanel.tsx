"use client";

import { fmt, fmtPx, sign } from "@/lib/format";
import { postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function PositionsPanel({ onAction }: { onAction?: (msg: string, ok: boolean) => void }) {
  const { positions, prices } = useLive();

  async function closeOne(tradeId: string) {
    if (!confirm("¿Cerrar esta posición a mercado?")) return;
    const r = await postJSON(`/api/close/${tradeId}`);
    onAction?.(r.ok ? "Cierre enviado" : `Error: ${r.error}`, !!r.ok);
  }

  async function closeAll() {
    if (!confirm("¿Cerrar TODAS las posiciones abiertas a mercado?")) return;
    const r = await postJSON<{ ok: boolean; closed: number }>("/api/close-all");
    onAction?.(r.closed ? `${r.closed} posición(es) cerrada(s)` : "No había posiciones", true);
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
              <span className="pos-pair">EUR/USD</span>
              <span className={`pos-pl ${pl >= 0 ? "pos" : "neg"}`}>{sign(pl)}</span>
              <button className="pos-close" title="Cerrar posición" onClick={() => closeOne(p.trade_id)}>
                ✕
              </button>
            </div>
            <div className="pos-mid">
              <span>Vol: <b>{fmt(p.units / 100000, 2)}</b></span>
              <span>Open: <b>{fmtPx(p.open_rate)}</b></span>
              <span>Cur: <b>{fmtPx(prices?.bid)}</b></span>
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
