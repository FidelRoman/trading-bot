"use client";
/* Estrategias de Trading editables en runtime. */

import { useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import type { BotSettings } from "@/lib/types";

export default function StrategiesPage() {
  const [activeStrategy, setActiveStrategy] = useState<string>("bollinger");
  const [values, setValues] = useState<Record<string, any>>({});
  const [expanded, setExpanded] = useState<string | null>("bollinger");
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    getJSON<BotSettings>("/api/settings").then((s) => {
      setActiveStrategy(s.active_strategy || "bollinger");
      setValues({
        timeframe: s.timeframe || "m15",
        bb_period: s.bb_period,
        bb_std: s.bb_std,
        atr_period: s.atr_period,
        sl_atr_mult: s.sl_atr_mult,
        min_band_width_pips: s.min_band_width_pips,
        rsi_period: s.rsi_period ?? 14,
        rsi_overbought: s.rsi_overbought ?? 70,
        rsi_oversold: s.rsi_oversold ?? 30,
      });
      if (s.active_strategy) {
        setExpanded(s.active_strategy);
      }
    }).catch(() => {});
  }, []);

  async function save(strategyKey: string) {
    const payload: Record<string, any> = {
      active_strategy: strategyKey,
      timeframe: values.timeframe || "m15",
      atr_period: values.atr_period,
      sl_atr_mult: values.sl_atr_mult,
    };
    if (strategyKey === "bollinger") {
      payload.bb_period = values.bb_period;
      payload.bb_std = values.bb_std;
      payload.min_band_width_pips = values.min_band_width_pips;
    } else if (strategyKey === "rsi") {
      payload.rsi_period = values.rsi_period;
      payload.rsi_overbought = values.rsi_overbought;
      payload.rsi_oversold = values.rsi_oversold;
    }

    const r = await postJSON<{ ok: boolean; settings: BotSettings }>("/api/settings", payload);
    if (r.ok) {
      setActiveStrategy(r.settings.active_strategy);
      setValues({
        timeframe: r.settings.timeframe || "m15",
        bb_period: r.settings.bb_period,
        bb_std: r.settings.bb_std,
        atr_period: r.settings.atr_period,
        sl_atr_mult: r.settings.sl_atr_mult,
        min_band_width_pips: r.settings.min_band_width_pips,
        rsi_period: r.settings.rsi_period,
        rsi_overbought: r.settings.rsi_overbought,
        rsi_oversold: r.settings.rsi_oversold,
      });
      setMsg({ text: `✓ Estrategia ${strategyKey === "bollinger" ? "Bollinger" : "RSI"} guardada y activada.`, ok: true });
    } else {
      setMsg({ text: "Error al guardar", ok: false });
    }
    setTimeout(() => setMsg(null), 5000);
  }

  const toggleExpand = (key: string) => {
    setExpanded(expanded === key ? null : key);
  };

  const selectTimeframe = (
    <label>
      TEMPORALIDAD (TIMEFRAME)
      <select
        value={values.timeframe ?? "m15"}
        onChange={(e) => setValues({ ...values, timeframe: e.target.value })}
        style={{
          background: "var(--card2)",
          border: "1px solid var(--border)",
          borderRadius: "8px",
          color: "var(--text)",
          fontSize: "14px",
          fontWeight: "600",
          padding: "11px 12px",
          outline: "none",
          marginTop: "7px"
        }}
      >
        <option value="m5">M5 — 5 minutos</option>
        <option value="m15">M15 — 15 minutos</option>
        <option value="m30">M30 — 30 minutos</option>
        <option value="h1">H1 — 1 hora</option>
        <option value="h4">H4 — 4 horas</option>
      </select>
    </label>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* BOLLINGER STRATEGY CARD */}
      <div className="card narrow" style={{ padding: 0, overflow: "hidden" }}>
        <div 
          className="accordion-header" 
          onClick={() => toggleExpand("bollinger")}
          style={{ background: "var(--card)", padding: "20px 24px" }}
        >
          <div className="strategy-title-row">
            <span className="strategy-name" style={{ fontSize: "16px" }}>Reversión a la Media (Bandas de Bollinger)</span>
            {activeStrategy === "bollinger" && <span className="chip ok ml">ACTIVA</span>}
          </div>
          <span className="arrow" style={{ fontSize: "14px" }}>{expanded === "bollinger" ? "▲" : "▼"}</span>
        </div>
        
        {expanded === "bollinger" && (
          <div className="accordion-content" style={{ padding: "24px", background: "var(--card)" }}>
            <div className="form-grid">
              {selectTimeframe}
              <label>
                PERÍODO BOLLINGER
                <input
                  type="number"
                  min={10}
                  max={50}
                  value={values.bb_period ?? ""}
                  onChange={(e) => setValues({ ...values, bb_period: +e.target.value })}
                />
              </label>
              <label>
                DESVIACIÓN STD
                <input
                  type="number"
                  min={1}
                  max={3}
                  step={0.1}
                  value={values.bb_std ?? ""}
                  onChange={(e) => setValues({ ...values, bb_std: +e.target.value })}
                />
              </label>
              <label>
                PERÍODO ATR
                <input
                  type="number"
                  min={5}
                  max={50}
                  value={values.atr_period ?? ""}
                  onChange={(e) => setValues({ ...values, atr_period: +e.target.value })}
                />
              </label>
              <label>
                MULT. STOP (×ATR)
                <input
                  type="number"
                  min={0.5}
                  max={5}
                  step={0.1}
                  value={values.sl_atr_mult ?? ""}
                  onChange={(e) => setValues({ ...values, sl_atr_mult: +e.target.value })}
                />
              </label>
              <label>
                ANCHO MÍN. BANDAS (PIPS)
                <input
                  type="number"
                  min={0}
                  max={50}
                  value={values.min_band_width_pips ?? ""}
                  onChange={(e) => setValues({ ...values, min_band_width_pips: +e.target.value })}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="btn btn-start" onClick={() => save("bollinger")}>
                {activeStrategy === "bollinger" ? "GUARDAR CAMBIOS" : "GUARDAR Y ACTIVAR"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* RSI STRATEGY CARD */}
      <div className="card narrow" style={{ padding: 0, overflow: "hidden" }}>
        <div 
          className="accordion-header" 
          onClick={() => toggleExpand("rsi")}
          style={{ background: "var(--card)", padding: "20px 24px" }}
        >
          <div className="strategy-title-row">
            <span className="strategy-name" style={{ fontSize: "16px" }}>Estrategia RSI (Relative Strength Index)</span>
            {activeStrategy === "rsi" && <span className="chip ok ml">ACTIVA</span>}
          </div>
          <span className="arrow" style={{ fontSize: "14px" }}>{expanded === "rsi" ? "▲" : "▼"}</span>
        </div>
        
        {expanded === "rsi" && (
          <div className="accordion-content" style={{ padding: "24px", background: "var(--card)" }}>
            <div className="form-grid">
              {selectTimeframe}
              <label>
                PERÍODO RSI
                <input
                  type="number"
                  min={5}
                  max={50}
                  value={values.rsi_period ?? ""}
                  onChange={(e) => setValues({ ...values, rsi_period: +e.target.value })}
                />
              </label>
              <label>
                LÍMITE SOBRECOMPRA
                <input
                  type="number"
                  min={50}
                  max={90}
                  value={values.rsi_overbought ?? ""}
                  onChange={(e) => setValues({ ...values, rsi_overbought: +e.target.value })}
                />
              </label>
              <label>
                LÍMITE SOBREVENTA
                <input
                  type="number"
                  min={10}
                  max={50}
                  value={values.rsi_oversold ?? ""}
                  onChange={(e) => setValues({ ...values, rsi_oversold: +e.target.value })}
                />
              </label>
              <label>
                PERÍODO ATR
                <input
                  type="number"
                  min={5}
                  max={50}
                  value={values.atr_period ?? ""}
                  onChange={(e) => setValues({ ...values, atr_period: +e.target.value })}
                />
              </label>
              <label>
                MULT. STOP (×ATR)
                <input
                  type="number"
                  min={0.5}
                  max={5}
                  step={0.1}
                  value={values.sl_atr_mult ?? ""}
                  onChange={(e) => setValues({ ...values, sl_atr_mult: +e.target.value })}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="btn btn-start" onClick={() => save("rsi")}>
                {activeStrategy === "rsi" ? "GUARDAR CAMBIOS" : "GUARDAR Y ACTIVAR"}
              </button>
            </div>
          </div>
        )}
      </div>

      {msg && (
        <div style={{ marginTop: 10, textAlign: "center" }}>
          <span className={`hint${msg.ok ? " ok" : " err"}`}>{msg.text}</span>
        </div>
      )}
    </div>
  );
}
