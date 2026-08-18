"use client";

import { useId, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import Mark from "./ui/Mark";
import { Panel } from "./ui/Panel";
import { useToast } from "./ui/Toast";
import { getJSON, postJSON } from "@/lib/api";
import { readAccount } from "@/lib/account";
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
    <div className="stepper">
      <button type="button" aria-label={`Reducir ${label}`} onClick={() => onChange(clamp(value - step))}>
        −
      </button>
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
      <button type="button" aria-label={`Aumentar ${label}`} onClick={() => onChange(clamp(value + step))}>
        +
      </button>
    </div>
  );
}

export default function StrategyControls() {
  const { status } = useLive();
  const { push } = useToast();
  const [lots, setLots] = useState(0.1);
  const [tp, setTp] = useState(20);
  const [sl, setSl] = useState(15);
  const [pendingSide, setPendingSide] = useState<"long" | "short" | null>(null);
  const [destination, setDestination] = useState("simulado");
  const [isReal, setIsReal] = useState(false);
  const [busy, setBusy] = useState(false);
  const lotsId = useId();
  const tpId = useId();
  const slId = useId();

  const account = readAccount(status);

  async function force(side: "long" | "short") {
    const detail = await getJSON<{ is_real: boolean; mode: string }>("/api/credentials").catch(
      () => null
    );
    setIsReal(Boolean(detail?.is_real));
    setDestination(detail?.is_real ? "cuenta real" : (detail?.mode ?? "simulado"));
    setPendingSide(side);
  }

  async function submitOrder() {
    if (!pendingSide) return;
    const side = pendingSide;
    const label = side === "long" ? "compra" : "venta";
    setBusy(true);
    try {
      const r = await postJSON<{ ok: boolean; units?: number; error?: string }>(
        `/api/manual/${side}`,
        { lots, sl_pips: sl, tp_pips: tp, acknowledge_real: isReal }
      );
      push(
        r.ok
          ? `Orden de ${label} enviada (${r.units ?? 0} unidades).`
          : (r.error ?? "No se pudo enviar la orden."),
        r.ok ? "ok" : "danger"
      );
      if (r.ok) setPendingSide(null);
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudo enviar la orden.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      label="Órdenes manuales"
      actions={
        <Mark tone={account.tone === "danger" ? "danger" : account.tone === "info" ? "info" : "warn"}>
          {account.label}
        </Mark>
      }
      caption="Van directas al bróker sin pasar por la estrategia. El control de riesgo diario sí se aplica."
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "var(--s-4)",
          alignItems: "end",
        }}
      >
        <div className="field">
          <label className="field-label" htmlFor={lotsId}>
            Tamaño (lotes)
          </label>
          <Stepper id={lotsId} label="tamaño en lotes" value={lots} onChange={setLots} step={0.01} min={0.01} max={5} decimals={2} />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={tpId}>
            Take profit (pips)
          </label>
          <Stepper id={tpId} label="take profit en pips" value={tp} onChange={setTp} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={slId}>
            Stop loss (pips)
          </label>
          <Stepper id={slId} label="stop loss en pips" value={sl} onChange={setSl} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div style={{ display: "grid", gap: "var(--s-2)" }}>
          <button className="btn long block" disabled={busy} onClick={() => force("long")}>
            Comprar
          </button>
          <button className="btn short block" disabled={busy} onClick={() => force("short")}>
            Vender
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={pendingSide !== null}
        title={`${pendingSide === "long" ? "Comprar" : "Vender"} ${status?.instrument ?? "instrumento"}`}
        description={
          <>
            Se enviará una orden de <strong>{lots} lotes</strong>, con stop loss de {sl} pips y
            take profit de {tp} pips, en <strong>{destination}</strong>.
          </>
        }
        consequence={isReal ? account.consequence : undefined}
        confirmLabel={isReal ? "Enviar en real" : "Enviar orden"}
        danger={isReal}
        busy={busy}
        onCancel={() => setPendingSide(null)}
        onConfirm={submitOrder}
      />
    </Panel>
  );
}
