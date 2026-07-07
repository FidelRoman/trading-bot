"use client";

import { useEffect, useState } from "react";
import { fmt } from "@/lib/format";
import { getJSON, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { BotSettings, Status } from "@/lib/types";

function Stepper({
  value,
  onChange,
  step,
  min,
  max,
  decimals,
}: {
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
      <button onClick={() => onChange(clamp(value - step))}>−</button>
      <input
        value={value.toFixed(decimals)}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!Number.isNaN(v)) onChange(clamp(v));
        }}
        inputMode="decimal"
      />
      <button onClick={() => onChange(clamp(value + step))}>＋</button>
    </div>
  );
}

export default function StrategyControls() {
  const { status, refreshStatus } = useLive();
  const [lots, setLots] = useState(0.1);
  const [tp, setTp] = useState(20);
  const [sl, setSl] = useState(15);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [bb, setBb] = useState("20,2");

  useEffect(() => {
    getJSON<BotSettings>("/api/settings")
      .then((s) => setBb(`${s.bb_period},${s.bb_std}`))
      .catch(() => {});
  }, []);

  function showMsg(text: string, ok: boolean) {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 6000);
  }

  async function force(side: "long" | "short") {
    const label = side === "long" ? "COMPRA" : "VENTA";
    if (!confirm(`¿Ejecutar ${label} manual de ${lots} lotes (SL ${sl} / TP ${tp} pips)?`)) return;
    const r = await postJSON<{ ok: boolean; units?: number; error?: string }>(
      `/api/manual/${side}`,
      { lots, sl_pips: sl, tp_pips: tp }
    );
    showMsg(r.ok ? `Orden ${label} enviada (${fmt(r.units ?? 0, 0)} unidades)` : `Error: ${r.error}`, !!r.ok);
  }

  async function toggleAuto(run: boolean) {
    await postJSON<{ ok: boolean; status: Status }>(`/api/control/${run ? "resume" : "pause"}`);
    await refreshStatus();
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">⚙ STRATEGY CONTROLS: BOLLINGER BB({bb})</div>
        <div className="auto-wrap">
          <span className="m-lbl">AUTO-TRADING</span>
          <label className="switch">
            <input
              type="checkbox"
              checked={!!status && !status.paused}
              onChange={(e) => toggleAuto(e.target.checked)}
            />
            <span className="track" />
          </label>
        </div>
      </div>
      <div className="controls-grid">
        <div className="ctl">
          <div className="m-lbl">LOT SIZE</div>
          <Stepper value={lots} onChange={setLots} step={0.01} min={0.01} max={5} decimals={2} />
        </div>
        <div className="ctl">
          <div className="m-lbl">TAKE PROFIT (PIPS)</div>
          <Stepper value={tp} onChange={setTp} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div className="ctl">
          <div className="m-lbl">STOP LOSS (PIPS)</div>
          <Stepper value={sl} onChange={setSl} step={0.5} min={1} max={200} decimals={1} />
        </div>
        <div className="ctl force-col">
          <button className="btn btn-buy" onClick={() => force("long")}>FORCE BUY</button>
          <button className="btn btn-sell" onClick={() => force("short")}>FORCE SELL</button>
        </div>
      </div>
      <div className={`manual-msg${msg ? (msg.ok ? " ok" : " err") : ""}`}>{msg?.text ?? ""}</div>
    </div>
  );
}
