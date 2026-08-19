"use client";

import { useState } from "react";
import AssetBadge from "./ui/AssetBadge";
import ConfirmDialog from "./ConfirmDialog";
import EmptyState from "./ui/EmptyState";
import Icon from "./ui/Icon";
import { Panel } from "./ui/Panel";
import { useReach } from "./ui/reach";
import { useToast } from "./ui/Toast";
import { signedMoney } from "@/lib/format";
import { formatPriceByAsset, formatVolumeByAsset } from "@/lib/instruments";
import { postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

export default function PositionsPanel() {
  const { positions, prices, status } = useLive();
  const { push } = useToast();
  const [pendingClose, setPendingClose] = useState<string | "all" | null>(null);
  const [busy, setBusy] = useState(false);
  const closeAllReach = useReach("positions");
  const digits = status?.digits ?? 5;
  const lotSize = status?.lot_size ?? 100000;
  const symbol = status?.instrument ?? "—";

  async function confirmClose() {
    if (!pendingClose) return;
    setBusy(true);
    try {
      const r =
        pendingClose === "all"
          ? await postJSON<{ ok: boolean; error?: string }>("/api/close-all")
          : await postJSON<{ ok: boolean; error?: string }>(`/api/close/${pendingClose}`);
      push(
        r.ok
          ? pendingClose === "all"
            ? "Cierre total enviado."
            : "Cierre enviado."
          : (r.error ?? "No se pudo enviar el cierre."),
        r.ok ? "ok" : "danger"
      );
      if (r.ok) setPendingClose(null);
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudo enviar el cierre.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      label="Posiciones abiertas"
      count={positions.length}
      actions={
        <button
          className="btn quiet danger"
          disabled={positions.length === 0 || busy}
          onClick={() => setPendingClose("all")}
          {...closeAllReach}
        >
          Cerrar todas
        </button>
      }
      bleed={positions.length === 0}
    >
      {positions.length === 0 ? (
        <EmptyState
          title="Ninguna posición abierta"
          hint="Cuando el bot o una orden manual abran posición, aparecerá aquí con su P&L en vivo."
        />
      ) : (
        <div style={{ display: "grid", gap: "var(--s-3)" }} data-reach-target="positions">
          {positions.map((p) => {
            const pl = p.gross_pl ?? 0;
            // Fracción de 0 a 1: $100 de P&L llena la barra entera.
            const width = Math.min(Math.abs(pl) / 100, 1);
            return (
              <article
                key={p.trade_id}
                style={{
                  display: "grid",
                  gap: "var(--s-2)",
                  padding: "var(--s-3)",
                  border: "1px solid var(--rule-faint)",
                  background: "var(--panel-inset)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "var(--s-2)", flexWrap: "wrap" }}>
                  <span
                    className={`mark ${p.side === "long" ? "ok" : "danger"}`}
                    style={{ fontWeight: 700, letterSpacing: "0.04em" }}
                  >
                    <span className="dot" />
                    {p.side === "long" ? "+ COMPRA ▲" : "− VENTA ▼"}
                  </span>
                  <AssetBadge
                    symbol={symbol}
                    assetClass={status?.asset_class}
                    size="sm"
                    showType={true}
                  />
                  <span className={`num ${pl >= 0 ? "pos" : "neg"}`} style={{ marginLeft: "auto", fontWeight: 700, fontSize: "var(--fs-md)" }}>
                    {signedMoney(pl)}
                  </span>
                  <button
                    className="btn quiet danger"
                    aria-label={`Cerrar posición ${p.side === "long" ? "compradora" : "vendedora"} de ${symbol}`}
                    disabled={busy}
                    onClick={() => setPendingClose(p.trade_id)}
                  >
                    <Icon name="close" size={13} />
                  </button>
                </div>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "var(--s-4)",
                    fontSize: "var(--fs-2xs)",
                    color: "var(--ink-3)",
                  }}
                >
                  <span>
                    Volumen <b className="num" style={{ color: "var(--ink)" }}>{formatVolumeByAsset(p.units, lotSize, status?.asset_class, symbol)}</b>
                  </span>
                  <span>
                    Apertura <b className="num" style={{ color: "var(--ink)" }}>{formatPriceByAsset(p.open_rate, symbol, status?.asset_class, digits)}</b>
                  </span>
                  <span>
                    Actual <b className="num" style={{ color: "var(--ink)" }}>{formatPriceByAsset(prices?.bid, symbol, status?.asset_class, digits)}</b>
                  </span>
                </div>
                <div className={`meter ${pl >= 0 ? "long" : "short"}`}>
                  <span style={{ "--fill": width } as React.CSSProperties} />
                </div>
              </article>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={pendingClose !== null}
        title={pendingClose === "all" ? "Cerrar todas las posiciones" : "Cerrar posición"}
        description={
          pendingClose === "all" ? (
            <>
              Se enviará el cierre a mercado de las{" "}
              <strong>{positions.length} posiciones abiertas</strong>. El precio final puede
              variar.
            </>
          ) : (
            <>Se enviará el cierre de esta posición a precio de mercado. El precio final puede variar.</>
          )
        }
        confirmLabel={pendingClose === "all" ? "Cerrar todas" : "Cerrar posición"}
        danger
        busy={busy}
        onCancel={() => setPendingClose(null)}
        onConfirm={confirmClose}
      />
    </Panel>
  );
}
