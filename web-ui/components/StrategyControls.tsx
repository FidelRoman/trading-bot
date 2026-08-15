"use client";

import { useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import { getJSON, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";

function Stepper({
  id,
  label,
  value,
  onChange,
  step,
  min,
  max,
  decimals,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (v: number) => void;
  step: number;
  min: number;
  max: number;
  decimals: number;
}) {
  const clamp = (v: number) => Math.min(Math.max(v, min), max);
  return (
    <div className="stepper" role="group" aria-labelledby={`${id}-label`}>
      <button type="button" aria-label={`Reducir ${label}`} onClick={() => onChange(clamp(value - step))}>−</button>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        aria-label={label}
        value={value.toFixed(decimals)}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!Number.isNaN(v)) onChange(clamp(v));
        }}
        inputMode="decimal"
      />
      <button type="button" aria-label={`Aumentar ${label}`} onClick={() => onChange(clamp(value + step))}>＋</button>
    </div>
  );
}

export default function StrategyControls() {
  const { status } = useLive();
  const [lots, setLots] = useState(0.1);
  const [tp, setTp] = useState(20);
  const [sl, setSl] = useState(15);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [pendingSide, setPendingSide] = useState<"long" | "short" | null>(null);
  const [destination, setDestination] = useState("simulado");
  const [isReal, setIsReal] = useState(false);
  const [busy, setBusy] = useState(false);

  function showMsg(text: string, ok: boolean) {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 6000);
  }

  async function force(side: "long" | "short") {
    setMsg(null);
    const account = await getJSON<{ is_real: boolean; mode: string }>("/api/credentials").catch(() => null);
    setIsReal(Boolean(account?.is_real));
    setDestination(account?.is_real ? "CUENTA REAL" : account?.mode ?? "simulado");
    setPendingSide(side);
  }

  async function submitOrder() {
    if (!pendingSide) return;
    const side = pendingSide;
    const label = side === "long" ? "COMPRA" : "VENTA";
    setBusy(true);
    try {
      const r = await postJSON<{ ok: boolean; units?: number; error?: string }>(
        `/api/manual/${side}`,
        { lots, sl_pips: sl, tp_pips: tp, acknowledge_real: isReal }
      );
      showMsg(r.ok ? `Orden de ${label.toLowerCase()} enviada (${r.units ?? 0} unidades).` : `Error: ${r.error}`, Boolean(r.ok));
      if (r.ok) setPendingSide(null);
    } catch (cause) {
      showMsg(cause instanceof Error ? cause.message : "No se pudo enviar la orden.", false);
    } finally {
      setBusy(false);
    }
  }

  const accountLabel = status?.live_execution
    ? status?.account?.connection === "Real" || status.mode.includes("real") ? "CUENTA REAL" : "CUENTA DEMO"
    : "SIMULADO";

  return (
    <section className="card" aria-labelledby="manual-orders-title">
      <div className="card-head">
        <h2 className="card-title" id="manual-orders-title">ÓRDENES MANUALES</h2>
        <span className={`chip${accountLabel === "CUENTA REAL" ? " real" : accountLabel === "CUENTA DEMO" ? " ok" : " warn"}`}>
          {accountLabel}
        </span>
      </div>
      <div className="controls-grid">
        <div className="ctl">
          <div className="m-lbl" id="lots-label">TAMAÑO (LOTES)</div>
          <Stepper id="lots" label="tamaño en lotes" value={lots} onChange={setLots} step={0.01} min={0.01} max={5} decimals={2} />
        </div>
        <div className="ctl">
          <div className="m-lbl" id="take-profit-label">TAKE PROFIT (PIPS)</div>
          <Stepper id="take-profit" label="take profit en pips" value={tp} onChange={setTp} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div className="ctl">
          <div className="m-lbl" id="stop-loss-label">STOP LOSS (PIPS)</div>
          <Stepper id="stop-loss" label="stop loss en pips" value={sl} onChange={setSl} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div className="ctl force-col">
          <button className="btn btn-buy" disabled={busy} onClick={() => force("long")}>COMPRAR</button>
          <button className="btn btn-sell" disabled={busy} onClick={() => force("short")}>VENDER</button>
        </div>
      </div>
      <div className={`manual-msg${msg ? (msg.ok ? " ok" : " err") : ""}`} role={msg?.ok ? "status" : "alert"} aria-live="polite">
        {msg?.text ?? ""}
      </div>
      <ConfirmDialog
        open={pendingSide !== null}
        title={`${pendingSide === "long" ? "Comprar" : "Vender"} ${status?.instrument ?? "instrumento"}`}
        description={<>Se enviará una orden de <strong>{lots} lotes</strong>, con SL de {sl} pips y TP de {tp} pips, en <strong>{destination}</strong>.</>}
        confirmLabel={isReal ? "ENVIAR EN REAL" : "ENVIAR ORDEN"}
        danger={isReal}
        busy={busy}
        onCancel={() => setPendingSide(null)}
        onConfirm={submitOrder}
      />
    </section>
  );
}
