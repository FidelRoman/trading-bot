"use client";
/* Ajustes del bot: estrategia y riesgo editables en runtime.
   Los porcentajes se muestran en % y se envían como fracción. */

import { useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import type { BotSettings } from "@/lib/types";

const FIELDS: {
  key: keyof BotSettings;
  label: string;
  min: number;
  max: number;
  step: number;
  pct?: boolean;
  group: "estrategia" | "riesgo";
}[] = [
  { key: "bb_period", label: "PERÍODO BOLLINGER", min: 10, max: 50, step: 1, group: "estrategia" },
  { key: "bb_std", label: "DESVIACIÓN STD", min: 1, max: 3, step: 0.1, group: "estrategia" },
  { key: "atr_period", label: "PERÍODO ATR", min: 5, max: 50, step: 1, group: "estrategia" },
  { key: "sl_atr_mult", label: "MULT. STOP (×ATR)", min: 0.5, max: 5, step: 0.1, group: "estrategia" },
  { key: "min_band_width_pips", label: "ANCHO MÍN. BANDAS (PIPS)", min: 0, max: 50, step: 1, group: "estrategia" },
  { key: "risk_per_trade", label: "RIESGO POR TRADE (%)", min: 0.1, max: 2, step: 0.1, pct: true, group: "riesgo" },
  { key: "daily_loss_limit", label: "LÍMITE PÉRDIDA DIARIA (%)", min: 1, max: 10, step: 0.5, pct: true, group: "riesgo" },
  { key: "max_trades_per_day", label: "MÁX. TRADES / DÍA", min: 1, max: 20, step: 1, group: "riesgo" },
  { key: "max_spread_pips", label: "SPREAD MÁX. (PIPS)", min: 0.5, max: 5, step: 0.1, group: "riesgo" },
  { key: "fixed_units", label: "UNIDADES FIJAS (0 = AUTO)", min: 0, max: 500000, step: 1000, group: "riesgo" },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    getJSON<BotSettings>("/api/settings").then((s) => {
      const v: Record<string, number> = {};
      for (const f of FIELDS) v[f.key] = f.pct ? +(s[f.key] * 100).toFixed(2) : s[f.key];
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
      for (const f of FIELDS) v[f.key] = f.pct ? +(r.settings[f.key] * 100).toFixed(2) : r.settings[f.key];
      setValues(v);
      setMsg({ text: "✓ Guardado — aplica desde la próxima vela.", ok: true });
    } else {
      setMsg({ text: "Error al guardar", ok: false });
    }
    setTimeout(() => setMsg(null), 5000);
  }

  const group = (g: "estrategia" | "riesgo") =>
    FIELDS.filter((f) => f.group === g).map((f) => (
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
    ));

  return (
    <div className="card narrow">
      <div className="card-head"><div className="card-title">⚙ BOT SETTINGS — ESTRATEGIA</div></div>
      <div className="form-grid">{group("estrategia")}</div>
      <div className="card-head mt"><div className="card-title">▲ BOT SETTINGS — RIESGO</div></div>
      <div className="form-grid">{group("riesgo")}</div>
      <div className="form-actions">
        <button className="btn btn-start" onClick={save}>GUARDAR AJUSTES</button>
        <span className={`hint${msg?.ok ? " ok" : ""}`}>
          {msg?.text ?? "Los cambios aplican desde la próxima vela."}
        </span>
      </div>
    </div>
  );
}
