"use client";

import { useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import { fmt, fmtPx, sign } from "@/lib/format";
import { postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function PositionsPanel({ onAction }: { onAction?: (msg: string, ok: boolean) => void }) {
  const { positions, prices, status } = useLive();
  const [pendingClose, setPendingClose] = useState<string | "all" | null>(null);
  const [busy, setBusy] = useState(false);
  const digits = status?.digits ?? 5;
  const lotSize = status?.lot_size ?? 100000;
  const symbol = status?.instrument ?? "—";

  async function confirmClose() {
    if (!pendingClose) return;
    setBusy(true);
    try {
      const r = pendingClose === "all"
        ? await postJSON<{ ok: boolean; error?: string }>("/api/close-all")
        : await postJSON<{ ok: boolean; error?: string }>(`/api/close/${pendingClose}`);
      onAction?.(r.ok ? (pendingClose === "all" ? "Cierre total enviado." : "Cierre enviado.") : `Error: ${r.error}`, Boolean(r.ok));
      if (r.ok) setPendingClose(null);
    } catch (cause) {
      onAction?.(cause instanceof Error ? cause.message : "No se pudo enviar el cierre.", false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="positions-title">
      <div className="card-head">
        <h2 className="card-title" id="positions-title">POSICIONES ABIERTAS ({positions.length})</h2>
        <button className="link-btn danger" disabled={positions.length === 0 || busy} onClick={() => setPendingClose("all")}>
          CERRAR TODAS
        </button>
      </div>
      {positions.length === 0 && <div className="empty">Sin posiciones abiertas</div>}
      {positions.map((p) => {
        const pl = p.gross_pl ?? 0;
        const barW = Math.min((Math.abs(pl) / 100) * 100, 100);
        return (
          <div className="pos-card" key={p.trade_id}>
            <div className="pos-top">
              <span className={`badge ${p.side === "long" ? "badge-buy" : "badge-sell"}`}>
                {p.side === "long" ? "COMPRA" : "VENTA"}
              </span>
              <span className="pos-pair">{symbol}</span>
              <span className={`pos-pl ${pl >= 0 ? "pos" : "neg"}`}>{sign(pl)}</span>
              <button
                className="pos-close"
                aria-label={`Cerrar posición ${p.side === "long" ? "compradora" : "vendedora"} de ${symbol}`}
                disabled={busy}
                onClick={() => setPendingClose(p.trade_id)}
              >
                ✕
              </button>
            </div>
            <div className="pos-mid">
              {/* 1 lote son 100.000 unidades solo en divisas; en acciones y
                  metales el lote lo define el bróker, así que se ven unidades. */}
              {lotSize >= 100000
                ? <span>Vol: <b>{fmt(p.units / lotSize, 2)}</b></span>
                : <span>Uds: <b>{fmt(p.units, 0)}</b></span>}
              <span>Apertura: <b>{fmtPx(p.open_rate, digits)}</b></span>
              <span>Actual: <b>{fmtPx(prices?.bid, digits)}</b></span>
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
      <ConfirmDialog
        open={pendingClose !== null}
        title={pendingClose === "all" ? "Cerrar todas las posiciones" : "Cerrar posición"}
        description={pendingClose === "all"
          ? <>Se enviará el cierre a mercado de las <strong>{positions.length} posiciones abiertas</strong>. El precio final puede variar.</>
          : <>Se enviará el cierre de esta posición a precio de mercado. El precio final puede variar.</>}
        confirmLabel={pendingClose === "all" ? "CERRAR TODAS" : "CERRAR POSICIÓN"}
        danger
        busy={busy}
        onCancel={() => setPendingClose(null)}
        onConfirm={confirmClose}
      />
    </section>
  );
}
