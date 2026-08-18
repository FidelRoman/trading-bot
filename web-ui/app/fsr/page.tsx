"use client";
/* Visor de la representación de la señal financiera.

   Muestra qué hace FSR con la ventana actual: cómo se descompone el precio en
   modos, qué exponente de Hurst tiene cada uno y cuáles se descartan por ruido.
   Es la página que permite entender —y desconfiar de— lo que ve el agente. */

import { useCallback, useEffect, useState } from "react";
import EmptyState from "@/components/ui/EmptyState";
import Mark from "@/components/ui/Mark";
import { Panel } from "@/components/ui/Panel";
import Readout, { ReadoutRow } from "@/components/ui/Readout";
import Skeleton from "@/components/ui/Skeleton";
import { TableFrame } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { getJSON, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { FsrPreview, TrainingState } from "@/lib/types";

const TIMEFRAMES = ["m15", "m30", "h1", "h4", "d1"];

/** Polilínea normalizada a la caja del SVG. */
function Spark({
  series,
  tone,
  height = 40,
  zero = false,
}: {
  series: number[];
  tone: "long" | "short" | "accent";
  height?: number;
  zero?: boolean;
}) {
  if (!series.length) return null;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const width = 100;
  const pts = series
    .map((v, i) => {
      const x = (i / (series.length - 1)) * width;
      const y = height - ((v - min) / span) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const yZero = height - ((0 - min) / span) * height;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Serie de ${series.length} puntos, mínimo ${min.toFixed(3)} y máximo ${max.toFixed(3)}`}
      style={{ width: "100%", height, display: "block" }}
    >
      {zero && min < 0 && max > 0 && (
        <line
          x1="0"
          y1={yZero}
          x2={width}
          y2={yZero}
          stroke="var(--plot-axis)"
          strokeWidth="0.4"
          strokeDasharray="2 2"
        />
      )}
      <polyline
        points={pts}
        fill="none"
        stroke={`var(--${tone})`}
        strokeWidth="1.2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Precio crudo y señal reconstruida en los mismos ejes. */
function Overlay({ prices, signal }: { prices: number[]; signal: number[] }) {
  const todos = [...prices, ...signal];
  const min = Math.min(...todos);
  const max = Math.max(...todos);
  const span = max - min || 1;
  const h = 220;
  const line = (s: number[]) =>
    s
      .map((v, i) => `${((i / (s.length - 1)) * 100).toFixed(2)},${(h - ((v - min) / span) * h).toFixed(2)}`)
      .join(" ");

  return (
    <svg
      viewBox={`0 0 100 ${h}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Comparación entre el precio original y la señal FSR reconstruida"
      style={{
        width: "100%",
        height: h,
        display: "block",
        borderBottom: "1px solid var(--rule)",
        borderLeft: "1px solid var(--rule)",
      }}
    >
      <polyline
        points={line(prices)}
        fill="none"
        stroke="var(--ink-3)"
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
      />
      <polyline
        points={line(signal)}
        fill="none"
        stroke="var(--long)"
        strokeWidth="1.6"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export default function FsrPage() {
  const { candleVersion } = useLive();
  const { push } = useToast();
  const [tf, setTf] = useState("h1");
  const [data, setData] = useState<FsrPreview | null>(null);
  const [cargando, setCargando] = useState(true);
  const [job, setJob] = useState<TrainingState | null>(null);

  const cargar = useCallback(async (timeframe: string) => {
    setCargando(true);
    try {
      setData(await getJSON<FsrPreview>(`/api/fsr?timeframe=${timeframe}`));
    } catch {
      setData(null);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar(tf);
  }, [tf, candleVersion, cargar]);

  useEffect(() => {
    const leer = () => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {});
    leer();
    const t = setInterval(leer, 2000);
    return () => clearInterval(t);
  }, []);

  const precalcular = async () => {
    await postJSON("/api/training/precompute", { timeframe: tf });
    push("Precálculo de la caché FSR lanzado.");
    setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
  };

  const corriendo = job?.status === "running";
  const precalculando = corriendo && job?.kind === "precompute";
  const progreso = Math.round((job?.progress ?? 0) * 100);
  const conservadas = data?.kept.filter(Boolean).length ?? 0;

  return (
    <div className="stack">
      <ReadoutRow label="Descomposición de la ventana actual">
        <Readout label="Ventana" value={data?.window ?? "—"} loading={cargando} note="Cierres que ve el agente" />
        <Readout label="Modos (IMF)" value={data?.imfs.length ?? "—"} loading={cargando} />
        <Readout
          label="Conservados"
          value={data ? `${conservadas} de ${data.imfs.length}` : "—"}
          loading={cargando}
          note="Los de memoria larga"
        />
        <Readout
          label="Ruido descartado"
          value={data ? `${(data.discarded_energy * 100).toFixed(1)}%` : "—"}
          loading={cargando}
          note="De la varianza de la ventana"
        />
      </ReadoutRow>

      <Panel
        label="Señal reconstruida frente al precio"
        actions={
          <>
            <label className="sr-only" htmlFor="fsr-timeframe">
              Temporalidad de la señal FSR
            </label>
            <select
              id="fsr-timeframe"
              className="select"
              style={{ width: "auto" }}
              value={tf}
              onChange={(e) => setTf(e.target.value)}
            >
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {t.toUpperCase()}
                </option>
              ))}
            </select>
            <button className="btn" onClick={() => cargar(tf)} disabled={cargando}>
              {cargando ? "Calculando…" : "Recalcular"}
            </button>
          </>
        }
        caption={
          data?.ok ? (
            <>
              <span style={{ color: "var(--ink-3)" }}>——— precio crudo</span> ·{" "}
              <span style={{ color: "var(--long)" }}>——— señal FSR</span>. La diferencia entre
              ambas es exactamente lo que el agente nunca llega a ver.
            </>
          ) : undefined
        }
      >
        {cargando ? (
          <Skeleton height={220} />
        ) : data?.ok ? (
          <Overlay prices={data.prices} signal={data.signal} />
        ) : (
          <EmptyState
            title="Sin datos suficientes para descomponer"
            hint={data?.error ?? "Hacen falta al menos tantas velas como cierres tiene la ventana."}
          />
        )}
      </Panel>

      <Panel
        label="Modos intrínsecos y memoria"
        actions={
          <button className="btn" onClick={precalcular} disabled={corriendo}>
            {precalculando ? `Precalculando ${progreso}%` : "Precalcular caché"}
          </button>
        }
        bleed
        caption="Los modos con Hurst ≤ 0,5 no tienen memoria: son las «olas» del paper y se eliminan. Los de Hurst > 0,5 conservan su tendencia durante un tiempo —las «mareas»— y se suman junto al residuo para formar la señal."
      >
        {precalculando && (
          <div style={{ padding: "var(--s-3) var(--s-4)" }} role="status" aria-live="polite">
            <div
              className="meter"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progreso}
              aria-label="Precálculo de la caché FSR"
            >
              <span style={{ "--fill": progreso / 100 } as React.CSSProperties} />
            </div>
            <p className="field-note" style={{ marginTop: "var(--s-2)" }}>
              {job?.note}
            </p>
          </div>
        )}

        {cargando ? (
          <div style={{ padding: "var(--s-4)" }}>
            <Skeleton height={28} count={4} />
          </div>
        ) : !data?.ok ? (
          <EmptyState title="Sin descomposición disponible" />
        ) : (
          <TableFrame>
            <table>
              <thead>
                <tr>
                  <th>Modo</th>
                  <th className="num">Hurst</th>
                  <th>Memoria</th>
                  <th>Destino</th>
                  <th style={{ width: "50%" }}>Forma</th>
                </tr>
              </thead>
              <tbody>
                {data.imfs.map((imf, i) => (
                  <tr key={i}>
                    <td>IMF {i + 1}</td>
                    <td className="num">{data.hursts[i]?.toFixed(3) ?? "—"}</td>
                    <td>{data.kept[i] ? "Larga" : "Corta"}</td>
                    <td>
                      <Mark tone={data.kept[i] ? "ok" : "danger"}>
                        {data.kept[i] ? "Se conserva" : "Se descarta"}
                      </Mark>
                    </td>
                    <td>
                      <Spark series={imf} tone={data.kept[i] ? "long" : "short"} zero />
                    </td>
                  </tr>
                ))}
                <tr>
                  <td>Residuo</td>
                  <td className="num">—</td>
                  <td>Tendencia</td>
                  <td>
                    <Mark tone="ok">Se conserva</Mark>
                  </td>
                  <td>
                    <Spark
                      series={data.signal.map(
                        (v, i) =>
                          v - data.imfs.reduce((a, imf, k) => a + (data.kept[k] ? imf[i] : 0), 0)
                      )}
                      tone="accent"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>
    </div>
  );
}
