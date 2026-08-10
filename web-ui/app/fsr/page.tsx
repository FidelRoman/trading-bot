"use client";
/* Visor de la representación de la señal financiera.

   Muestra qué hace FSR con la ventana actual: cómo se descompone el precio en
   modos, qué exponente de Hurst tiene cada uno y cuáles se descartan por ruido.
   Es la pestaña que permite entender —y desconfiar de— lo que ve el agente. */

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { FsrPreview, TrainingState } from "@/lib/types";

const TIMEFRAMES = ["m15", "m30", "h1", "h4", "d1"];

/** Polilínea normalizada a la caja del SVG. */
function Spark({
  series,
  color,
  height = 60,
  zero = false,
}: {
  series: number[];
  color: string;
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
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none"
         style={{ width: "100%", height, display: "block" }}>
      {zero && min < 0 && max > 0 && (
        <line x1="0" y1={yZero} x2={width} y2={yZero}
              stroke="rgba(148,163,184,.35)" strokeWidth="0.4" strokeDasharray="2 2" />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.2"
                vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Precio crudo y señal reconstruida en los mismos ejes. */
function Overlay({ prices, signal }: { prices: number[]; signal: number[] }) {
  const todos = [...prices, ...signal];
  const min = Math.min(...todos);
  const max = Math.max(...todos);
  const span = max - min || 1;
  const h = 200;
  const line = (s: number[]) =>
    s.map((v, i) => `${((i / (s.length - 1)) * 100).toFixed(2)},${(h - ((v - min) / span) * h).toFixed(2)}`).join(" ");

  return (
    <svg viewBox={`0 0 100 ${h}`} preserveAspectRatio="none"
         style={{ width: "100%", height: h, display: "block" }}>
      <polyline points={line(prices)} fill="none" stroke="rgba(148,163,184,.55)"
                strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <polyline points={line(signal)} fill="none" stroke="#4ade80"
                strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function FsrPage() {
  const { candleVersion } = useLive();
  const [tf, setTf] = useState("h1");
  const [data, setData] = useState<FsrPreview | null>(null);
  const [cargando, setCargando] = useState(false);
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

  useEffect(() => { cargar(tf); }, [tf, candleVersion, cargar]);

  useEffect(() => {
    const leer = () => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {});
    leer();
    const t = setInterval(leer, 2000);
    return () => clearInterval(t);
  }, []);

  const precalcular = async () => {
    await postJSON("/api/training/precompute", { timeframe: tf });
    setTimeout(() => getJSON<TrainingState>("/api/training").then(setJob).catch(() => {}), 300);
  };

  const corriendo = job?.status === "running";
  const conservadas = data?.kept.filter(Boolean).length ?? 0;

  return (
    <>
      <div className="metric-row inner">
        <div className="metric-card">
          <div className="m-lbl">VENTANA</div>
          <div className="m-val">{data?.window ?? "—"}</div>
        </div>
        <div className="metric-card">
          <div className="m-lbl">MODOS (IMF)</div>
          <div className="m-val">{data?.imfs.length ?? "—"}</div>
        </div>
        <div className="metric-card">
          <div className="m-lbl">CONSERVADOS</div>
          <div className="m-val">{data ? `${conservadas}/${data.imfs.length}` : "—"}</div>
        </div>
        <div className="metric-card">
          <div className="m-lbl">RUIDO DESCARTADO</div>
          <div className="m-val">
            {data ? `${(data.discarded_energy * 100).toFixed(1)}%` : "—"}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">∿ SEÑAL RECONSTRUIDA vs PRECIO</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select value={tf} onChange={(e) => setTf(e.target.value)}>
              {TIMEFRAMES.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
            </select>
            <button className="btn" onClick={() => cargar(tf)} disabled={cargando}>
              {cargando ? "CALCULANDO…" : "RECALCULAR"}
            </button>
          </div>
        </div>

        {data?.ok ? (
          <>
            <Overlay prices={data.prices} signal={data.signal} />
            <div className="hint" style={{ padding: "6px 12px" }}>
              <span style={{ color: "rgba(148,163,184,.9)" }}>▬ precio crudo</span>
              {"   "}
              <span style={{ color: "#4ade80" }}>▬ señal FSR</span>
              {"   "}— la diferencia entre ambas es exactamente lo que el agente
              nunca llega a ver.
            </div>
          </>
        ) : (
          <div className="empty">{data?.error ?? "Sin datos suficientes para descomponer"}</div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">◫ MODOS INTRÍNSECOS Y MEMORIA (HURST)</div>
          <button className="btn" onClick={precalcular} disabled={corriendo}>
            {corriendo && job?.kind === "precompute"
              ? `PRECALCULANDO ${Math.round((job.progress ?? 0) * 100)}%`
              : "PRECALCULAR CACHÉ"}
          </button>
        </div>

        {corriendo && job?.kind === "precompute" && (
          <div style={{ padding: "0 12px 10px" }}>
            <div style={{ height: 6, background: "rgba(148,163,184,.15)", borderRadius: 3 }}>
              <div style={{
                width: `${(job.progress ?? 0) * 100}%`, height: "100%",
                background: "#4ade80", borderRadius: 3, transition: "width .4s",
              }} />
            </div>
            <div className="hint" style={{ marginTop: 6 }}>{job.note}</div>
          </div>
        )}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>MODO</th><th>HURST</th><th>MEMORIA</th><th>DESTINO</th><th style={{ width: "50%" }}>FORMA</th>
              </tr>
            </thead>
            <tbody>
              {data?.ok && data.imfs.map((imf, i) => (
                <tr key={i}>
                  <td>IMF {i + 1}</td>
                  <td>{data.hursts[i]?.toFixed(3) ?? "—"}</td>
                  <td>{data.kept[i] ? "larga" : "corta"}</td>
                  <td className={data.kept[i] ? "pos" : "neg"}>
                    {data.kept[i] ? "SE CONSERVA" : "SE DESCARTA"}
                  </td>
                  <td><Spark series={imf} color={data.kept[i] ? "#4ade80" : "#f0716a"} height={40} zero /></td>
                </tr>
              ))}
              {data?.ok && (
                <tr>
                  <td>RESIDUO</td>
                  <td>—</td>
                  <td>tendencia</td>
                  <td className="pos">SE CONSERVA</td>
                  <td>
                    <Spark
                      series={data.signal.map((v, i) =>
                        v - data.imfs.reduce((a, imf, k) => a + (data.kept[k] ? imf[i] : 0), 0))}
                      color="#60a5fa"
                      height={40}
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {!data?.ok && <div className="empty">Sin descomposición disponible</div>}
        </div>
        <div className="hint" style={{ padding: "8px 12px" }}>
          Los modos con Hurst ≤ 0.5 no tienen memoria: son las &quot;olas&quot; del paper y se
          eliminan. Los de Hurst &gt; 0.5 conservan su tendencia durante un tiempo
          —las &quot;mareas&quot;— y se suman junto al residuo para formar la señal.
        </div>
      </div>
    </>
  );
}
