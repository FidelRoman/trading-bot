"use client";
/* Ajustes de control de riesgo y credenciales. */

import { useEffect, useState } from "react";
import AccountCard from "@/components/AccountCard";
import { getJSON, postJSON } from "@/lib/api";
import type { BotSettings } from "@/lib/types";
import { useLive } from "@/lib/live";

const FIELDS: {
  key: keyof BotSettings;
  label: string;
  min: number;
  max: number;
  step: number;
  pct?: boolean;
}[] = [
  { key: "risk_per_trade", label: "RIESGO POR TRADE (%)", min: 0.1, max: 2, step: 0.1, pct: true },
  { key: "daily_loss_limit", label: "LÍMITE PÉRDIDA DIARIA (%)", min: 1, max: 10, step: 0.5, pct: true },
  { key: "max_trades_per_day", label: "MÁX. TRADES / DÍA", min: 1, max: 20, step: 1 },
  { key: "max_spread_pips", label: "SPREAD MÁX. (PIPS) — SOLO DIVISAS", min: 0.5, max: 5, step: 0.1 },
  { key: "max_spread_bps", label: "SPREAD MÁX. (BPS) — TODOS LOS ACTIVOS", min: 0.1, max: 100, step: 0.1 },
  { key: "fixed_units", label: "UNIDADES FIJAS (0 = AUTO)", min: 0, max: 500000, step: 1000 },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const { status, refreshStatus } = useLive();
  const [busyConn, setBusyConn] = useState(false);

  async function setConnection(conn: string) {
    if (conn === "Real") {
      if (!confirm("¿Enviar órdenes a la CUENTA REAL?")) return;
    }
    setBusyConn(true);
    const r = await postJSON<{ ok: boolean }>("/api/credentials", { connection: conn });
    setBusyConn(false);
    if (r.ok) refreshStatus();
  }

  const conn = status?.account?.connection ?? "auto";

  useEffect(() => {
    getJSON<BotSettings>("/api/settings").then((s) => {
      const v: Record<string, number> = {};
      for (const f of FIELDS) v[f.key] = f.pct ? +((s[f.key] as number) * 100).toFixed(2) : (s[f.key] as number);
      setValues(v);
    }).catch(() => {});
  }, []);

  async function save() {
    const payload: Record<string, number> = {};
    for (const f of FIELDS) {
      const raw = values[f.key];
      if (raw == null || Number.isNaN(raw)) continue;
      payload[f.key] = f.pct ? raw / 100 : raw;
    }
    const r = await postJSON<{ ok: boolean; settings: BotSettings }>("/api/settings", payload);
    if (r.ok) {
      const v: Record<string, number> = {};
      for (const f of FIELDS) v[f.key] = f.pct ? +((r.settings[f.key] as number) * 100).toFixed(2) : (r.settings[f.key] as number);
      setValues(v);
      setMsg({ text: "✓ Guardado con éxito.", ok: true });
    } else {
      setMsg({ text: "Error al guardar", ok: false });
    }
    setTimeout(() => setMsg(null), 5000);
  }

  return (
    <>
    <div className="card narrow mb" style={{ marginBottom: "16px" }}>
      <div className="card-head"><div className="card-title">CUENTA DE EJECUCIÓN</div></div>
      <div style={{ padding: "16px" }}>
        <select
          value={conn}
          onChange={(e) => setConnection(e.target.value)}
          disabled={busyConn}
          style={{ width: "100%", background: "var(--card2)", border: "1px solid var(--border)", borderRadius: "6px", color: "var(--text)", fontSize: "13px", fontWeight: "600", padding: "6px 12px", outline: "none" }}
        >
          <option value="auto" disabled>Detectando...</option>
          <option value="Demo">Demo</option>
          <option value="Real">Real</option>
        </select>
        {conn === "Real" && (
          <div style={{ color: "#f0716a", fontSize: "11px", marginTop: "8px", fontWeight: "bold" }}>
            Aviso: Las órdenes van a dinero real.
          </div>
        )}
      </div>
    </div>
    <AccountCard />
    <div className="card narrow">
      <div className="card-head"><div className="card-title">▲ BOT SETTINGS — RIESGO</div></div>
      <div className="form-grid">
        {FIELDS.map((f) => (
          <label key={f.key}>
            {f.label}
            <input
              type="number"
              min={f.min}
              max={f.max}
              step={f.step}
              value={values[f.key] ?? ""}
              onChange={(e) => setValues({ ...values, [f.key]: +e.target.value })}
            />
          </label>
        ))}
      </div>
      <div className="form-actions">
        <button className="btn btn-start" onClick={save}>GUARDAR AJUSTES</button>
        <span className={`hint${msg?.ok ? " ok" : ""}`}>
          {msg?.text ?? "Los cambios de riesgo se aplican de inmediato."}
        </span>
      </div>
    </div>
    </>
  );
}
