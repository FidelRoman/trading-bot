"use client";
/* Wrappers React para lightweight-charts. Solo cliente.
   Los colores salen de los tokens de la lámina, no de hexadecimales copiados:
   así la figura cambia de soporte con el resto de la interfaz. */

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  type DeepPartial,
  type ChartOptions,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { Band, Candle } from "@/lib/types";

/** Lee un token del documento. Los gráficos no pueden usar variables CSS. */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Se incrementa cuando cambia el soporte, para rehacer la figura con él. */
export function useSupportTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const bump = () => setTick((value) => value + 1);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", bump);
    const observer = new MutationObserver(bump);
    observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    return () => {
      media.removeEventListener("change", bump);
      observer.disconnect();
    };
  }, []);
  return tick;
}

function chartOptions(): DeepPartial<ChartOptions> {
  const grid = token("--plot-grid", "rgba(20,23,26,0.08)");
  const axis = token("--plot-axis", "rgba(20,23,26,0.24)");
  const crosshair = token("--plot-crosshair", "rgba(31,79,168,0.45)");
  const label = token("--panel", "#f8f6f1");
  return {
    layout: {
      background: { color: "transparent" },
      textColor: token("--ink-3", "#7c8188"),
      fontFamily: `var(--font-sans), system-ui, sans-serif`,
      fontSize: 11,
    },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderColor: axis },
    timeScale: { borderColor: axis, timeVisible: true, secondsVisible: false },
    crosshair: {
      vertLine: { color: crosshair, labelBackgroundColor: label },
      horzLine: { color: crosshair, labelBackgroundColor: label },
    },
    autoSize: true,
  };
}

export function CandleChart({
  candles,
  bands,
  markers,
  digits = 5,
  label = "Gráfico de velas",
  tall,
}: {
  candles: Candle[];
  bands: Band[];
  markers?: SeriesMarker<Time>[];
  digits?: number;
  label?: string;
  tall?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const tick = useSupportTick();

  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    const long = token("--long", "#0a6b4a");
    const short = token("--short", "#ae2a20");
    const accent = token("--accent", "#1f4fa8");
    const chart = createChart(ref.current, chartOptions());
    const series = chart.addCandlestickSeries({
      upColor: long,
      downColor: short,
      wickUpColor: long,
      wickDownColor: short,
      borderVisible: false,
      priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
    });
    series.setData(
      candles as { time: Time; open: number; high: number; low: number; close: number }[]
    );
    const mkLine = (color: string, style: number) =>
      chart.addLineSeries({
        color,
        lineWidth: 1,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    mkLine(accent, 2).setData(bands.map((b) => ({ time: b.time as Time, value: b.upper })));
    mkLine(accent, 2).setData(bands.map((b) => ({ time: b.time as Time, value: b.lower })));
    mkLine(token("--ink-3", "#7c8188"), 0).setData(
      bands.map((b) => ({ time: b.time as Time, value: b.mid }))
    );
    if (markers?.length) series.setMarkers(markers);
    return () => chart.remove();
  }, [candles, bands, markers, digits, tick]);

  const latest = candles[candles.length - 1];
  const summary = latest
    ? `${label}. ${candles.length} velas. Último cierre ${latest.close.toFixed(digits)}, máximo ${latest.high.toFixed(digits)}, mínimo ${latest.low.toFixed(digits)}.`
    : `${label}. Sin datos disponibles.`;

  return <div ref={ref} className={`figure${tall ? " tall" : ""}`} role="img" aria-label={summary} />;
}

export function AreaChart({
  data,
  tone = "accent",
  fit,
  short,
  label = "Gráfico de evolución",
}: {
  data: { time: number; value: number }[];
  tone?: "accent" | "long" | "short";
  fit?: boolean;
  short?: boolean;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const tick = useSupportTick();

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const color = token(`--${tone}`, "#1f4fa8");
    const chart = createChart(ref.current, chartOptions());
    const series = chart.addAreaSeries({
      lineColor: color,
      lineWidth: 2,
      topColor: token(`--${tone}-wash`, "rgba(31,79,168,0.1)"),
      bottomColor: "transparent",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    series.setData(data as { time: Time; value: number }[]);
    if (fit) chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, tone, fit, tick]);

  const values = data.map((point) => point.value);
  const summary = values.length
    ? `${label}. ${values.length} puntos. Último valor ${values[values.length - 1].toFixed(2)}, mínimo ${Math.min(...values).toFixed(2)}, máximo ${Math.max(...values).toFixed(2)}.`
    : `${label}. Sin datos disponibles.`;
  return (
    <div ref={ref} className={`figure${short ? " short" : ""}`} role="img" aria-label={summary} />
  );
}
