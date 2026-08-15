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
  const [busy, setBusy] = useState(false);
  const [timeframeMsg, setTimeframeMsg] = useState("");
  // Con FSRPPO y modelo activo el reloj lo fija el modelo: el ajuste queda inerte
  // y hay que decirlo, no dejar un campo que aparenta hacer algo y no lo hace.
  const tfLoManda = status?.timeframe_source === "modelo";
  const tf = status?.timeframe_setting ?? status?.timeframe ?? "h1";

  async function setTimeframe(valor: string) {
    setTimeframeMsg("");
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/settings", { timeframe: valor });
      if (!r.ok) throw new Error(r.error || "No se pudo cambiar la temporalidad.");
      await refreshStatus();
      setTimeframeMsg(`Temporalidad actualizada a ${valor.toUpperCase()}.`);
    } catch (cause) {
      setTimeframeMsg(cause instanceof Error ? cause.message : "No se pudo cambiar la temporalidad.");
    }
  }

  useEffect(() => {
    getJSON<BotSettings>("/api/settings").then((s) => {
      const v: Record<string, number> = {};
      for (const f of FIELDS) v[f.key] = f.pct ? +((s[f.key] as number) * 100).toFixed(2) : (s[f.key] as number);
      setValues(v);
    }).catch(() => setMsg({ text: "No se pudieron cargar los límites de riesgo.", ok: false }));
  }, []);

  async function save() {
    setBusy(true);
    setMsg(null);
    const payload: Record<string, number> = {};
    for (const f of FIELDS) {
      const raw = values[f.key];
      if (raw == null || Number.isNaN(raw)) continue;
      payload[f.key] = f.pct ? raw / 100 : raw;
    }
    try {
      const r = await postJSON<{ ok: boolean; error?: string; settings: BotSettings }>("/api/settings", payload);
      if (!r.ok) throw new Error(r.error || "Error al guardar los límites de riesgo.");
      const next: Record<string, number> = {};
      for (const f of FIELDS) next[f.key] = f.pct ? +((r.settings[f.key] as number) * 100).toFixed(2) : (r.settings[f.key] as number);
      setValues(next);
      setMsg({ text: "Guardado con éxito.", ok: true });
    } catch (cause) {
      setMsg({ text: cause instanceof Error ? cause.message : "Error al guardar.", ok: false });
    } finally {
      setBusy(false);
    }
    setTimeout(() => setMsg(null), 5000);
  }

  return (
    <>
    <AccountCard />
    <section className="card narrow mb" aria-labelledby="clock-title">
      <div className="card-head">
        <h2 className="card-title" id="clock-title">RELOJ DE DECISIÓN</h2>
        <span className="chip">{(status?.timeframe ?? "—").toUpperCase()}</span>
      </div>
      <div className="card-body">
        <label className="field-label" htmlFor="decision-timeframe">TEMPORALIDAD</label>
        <select
          id="decision-timeframe"
          value={tf}
          disabled={tfLoManda}
          onChange={(e) => setTimeframe(e.target.value)}
          className="field-control"
        >
          {["m5", "m15", "m30", "h1", "h4", "d1"].map((t) => (
            <option key={t} value={t}>{t.toUpperCase()}</option>
          ))}
        </select>
        <div className="hint" style={{ marginTop: 8 }}>
          {tfLoManda ? (
            <>Lo fija el <strong>modelo activo</strong>, que se entrenó en{" "}
            {status?.active_model_timeframe?.toUpperCase()}. Darle velas de otro
            tamaño invalidaría sus pesos en silencio. Para elegirlo a mano, desactiva
            el modelo en Modelos.</>
          ) : (
            <>El bot decide una vez por cada vela cerrada de este tamaño. Con FSRPPO
            y un modelo activo, este ajuste se ignora y manda el del modelo.</>
          )}
        </div>
        {timeframeMsg && <div className="manual-msg" role="status" aria-live="polite">{timeframeMsg}</div>}
      </div>
    </section>
    <section className="card narrow" aria-labelledby="risk-title">
      <div className="card-head"><h2 className="card-title" id="risk-title">LÍMITES DE RIESGO</h2></div>
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
        <button className="btn btn-start" onClick={save} disabled={busy}>
          {busy ? "GUARDANDO…" : "GUARDAR AJUSTES"}
        </button>
        <span className={`hint${msg ? (msg.ok ? " ok" : " err") : ""}`} role="status" aria-live="polite">
          {msg?.text ?? "Los cambios de riesgo se aplican de inmediato."}
        </span>
      </div>
    </section>
    </>
  );
}
