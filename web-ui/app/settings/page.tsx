"use client";
/* Ajustes de control de riesgo y credenciales.

   Cada límite dice ahora qué implica: antes eran seis casillas numéricas sin
   ninguna pista de qué pasaba al moverlas, en la página que decide cuánto se
   puede llegar a perder en un día. */

import { useEffect, useState } from "react";
import AccountCard from "@/components/AccountCard";
import Mark from "@/components/ui/Mark";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import Skeleton from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { getJSON, postJSON } from "@/lib/api";
import { fmt } from "@/lib/format";
import type { BotSettings } from "@/lib/types";
import { useLive } from "@/lib/live";

const FIELDS: {
  key: keyof BotSettings;
  label: string;
  min: number;
  max: number;
  step: number;
  pct?: boolean;
  note: (equity: number | undefined, value: number) => React.ReactNode;
}[] = [
  {
    key: "risk_per_trade",
    label: "Riesgo por operación (%)",
    min: 0.1,
    max: 2,
    step: 0.1,
    pct: true,
    note: (equity, value) =>
      equity
        ? `Cada operación arriesga unos $${fmt((equity * value) / 100)} con el capital actual.`
        : "Porcentaje del capital que se arriesga en cada entrada.",
  },
  {
    key: "daily_loss_limit",
    label: "Límite de pérdida diaria (%)",
    min: 1,
    max: 10,
    step: 0.5,
    pct: true,
    note: (equity, value) =>
      equity
        ? `Al perder $${fmt((equity * value) / 100)} en un día, el bot se pausa hasta el siguiente.`
        : "Al alcanzarlo, el bot se pausa hasta el día siguiente.",
  },
  {
    key: "max_trades_per_day",
    label: "Máximo de operaciones al día",
    min: 1,
    max: 20,
    step: 1,
    note: () => "Alcanzado el tope, no se abren más entradas hasta mañana.",
  },
  {
    key: "max_spread_pips",
    label: "Spread máximo en pips",
    min: 0.5,
    max: 5,
    step: 0.1,
    note: () => "Solo se aplica a divisas. Por encima, el bot no entra.",
  },
  {
    key: "max_spread_bps",
    label: "Spread máximo en puntos básicos",
    min: 0.1,
    max: 100,
    step: 0.1,
    note: () => "Se aplica a todos los activos, incluidos índices y acciones.",
  },
  {
    key: "fixed_units",
    label: "Unidades fijas",
    min: 0,
    max: 500000,
    step: 1000,
    note: (_e, value) =>
      value > 0
        ? "Mandan estas unidades: el riesgo por operación queda inerte."
        : "0 = el tamaño se calcula con el riesgo por operación.",
  },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, number>>({});
  const [loaded, setLoaded] = useState(false);
  const { status, refreshStatus } = useLive();
  const { push } = useToast();
  const [busy, setBusy] = useState(false);

  // Con FSRPPO y modelo activo el reloj lo fija el modelo: el ajuste queda inerte
  // y hay que decirlo, no dejar un campo que aparenta hacer algo y no lo hace.
  const modelRules = status?.timeframe_source === "modelo";
  const tf = status?.timeframe_setting ?? status?.timeframe ?? "h1";
  const equity = status?.account?.equity;

  async function setTimeframe(value: string) {
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/settings", {
        timeframe: value,
      });
      if (!r.ok) throw new Error(r.error || "No se pudo cambiar la temporalidad.");
      await refreshStatus();
      push(`Temporalidad actualizada a ${value.toUpperCase()}.`);
    } catch (cause) {
      push(
        cause instanceof Error ? cause.message : "No se pudo cambiar la temporalidad.",
        "danger"
      );
    }
  }

  useEffect(() => {
    getJSON<BotSettings>("/api/settings")
      .then((s) => {
        const next: Record<string, number> = {};
        for (const f of FIELDS)
          next[f.key] = f.pct ? +((s[f.key] as number) * 100).toFixed(2) : (s[f.key] as number);
        setValues(next);
        setLoaded(true);
      })
      .catch(() => {
        push("No se pudieron cargar los límites de riesgo.", "danger");
        setLoaded(true);
      });
  }, [push]);

  async function save() {
    setBusy(true);
    const payload: Record<string, number> = {};
    for (const f of FIELDS) {
      const raw = values[f.key];
      if (raw == null || Number.isNaN(raw)) continue;
      payload[f.key] = f.pct ? raw / 100 : raw;
    }
    try {
      const r = await postJSON<{ ok: boolean; error?: string; settings: BotSettings }>(
        "/api/settings",
        payload
      );
      if (!r.ok) throw new Error(r.error || "Error al guardar los límites de riesgo.");
      const next: Record<string, number> = {};
      for (const f of FIELDS)
        next[f.key] = f.pct
          ? +((r.settings[f.key] as number) * 100).toFixed(2)
          : (r.settings[f.key] as number);
      setValues(next);
      push("Límites de riesgo guardados. Se aplican de inmediato.");
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "Error al guardar.", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <AccountCard />

      <Panel
        label="Reloj de decisión"
        actions={<Mark tone="info">{(status?.timeframe ?? "—").toUpperCase()}</Mark>}
        caption={
          modelRules ? (
            <>
              Lo fija el <strong>modelo activo</strong>, que se entrenó en{" "}
              {status?.active_model_timeframe?.toUpperCase()}. Darle velas de otro tamaño
              invalidaría sus pesos en silencio. Para elegirlo a mano, desactiva el modelo en
              Modelos.
            </>
          ) : (
            <>
              El bot decide una vez por cada vela cerrada de este tamaño. Con FSRPPO y un modelo
              activo, este ajuste se ignora y manda el del modelo.
            </>
          )
        }
      >
        <div className="field" style={{ maxWidth: 280 }}>
          <label className="field-label" htmlFor="decision-timeframe">
            Temporalidad
          </label>
          <select
            id="decision-timeframe"
            className="select"
            value={tf}
            disabled={modelRules}
            onChange={(e) => setTimeframe(e.target.value)}
          >
            {["m5", "m15", "m30", "h1", "h4", "d1"].map((t) => (
              <option key={t} value={t}>
                {t.toUpperCase()}
              </option>
            ))}
          </select>
        </div>
      </Panel>

      <Panel
        label="Límites de riesgo"
        caption="Este es el control que veta al agente: por muy convencida que esté la política, ninguna decisión pasa de estos números. Los cambios se aplican de inmediato."
      >
        {!loaded ? (
          <Skeleton height={30} count={6} />
        ) : (
          <>
            {values.fixed_units > 0 && (
              <div style={{ marginBottom: "var(--s-4)" }}>
                <Notice tone="warn" title="Tamaño fijo activo.">
                  Con unidades fijas, el riesgo por operación no dimensiona nada: cada entrada usa{" "}
                  {fmt(values.fixed_units, 0)} unidades pase lo que pase.
                </Notice>
              </div>
            )}
            <div className="field-grid">
              {FIELDS.map((f) => (
                <div className="field" key={f.key}>
                  <label className="field-label" htmlFor={String(f.key)}>
                    {f.label}
                  </label>
                  <input
                    id={String(f.key)}
                    className="input"
                    type="number"
                    min={f.min}
                    max={f.max}
                    step={f.step}
                    value={values[f.key] ?? ""}
                    disabled={f.key === "risk_per_trade" && values.fixed_units > 0}
                    onChange={(e) => setValues({ ...values, [f.key]: +e.target.value })}
                  />
                  <span className="field-note">{f.note(equity, values[f.key] ?? 0)}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: "var(--s-5)" }}>
              <button className="btn primary" onClick={save} disabled={busy}>
                {busy ? "Guardando…" : "Guardar límites"}
              </button>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
