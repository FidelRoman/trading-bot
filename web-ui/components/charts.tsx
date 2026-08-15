"use client";
/* Wrappers React para lightweight-charts. Solo cliente. */

import { useEffect, useRef } from "react";
import {
  createChart,
  type DeepPartial,
  type ChartOptions,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { Band, Candle } from "@/lib/types";

export const CHART_OPTS: DeepPartial<ChartOptions> = {
  layout: {
    background: { color: "transparent" },
    textColor: "#8a90a0",
    fontFamily: '"JetBrains Mono", monospace',
  },
  grid: {
    vertLines: { color: "rgba(138,144,160,0.07)" },
    horzLines: { color: "rgba(138,144,160,0.07)" },
  },
  rightPriceScale: { borderColor: "rgba(138,144,160,0.18)" },
  timeScale: { borderColor: "rgba(138,144,160,0.18)", timeVisible: true, secondsVisible: false },
  crosshair: {
    vertLine: { color: "rgba(154,168,248,0.4)", labelBackgroundColor: "#16181e" },
    horzLine: { color: "rgba(154,168,248,0.4)", labelBackgroundColor: "#16181e" },
  },
  autoSize: true,
};

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

  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    const chart = createChart(ref.current, CHART_OPTS);
    const series = chart.addCandlestickSeries({
      upColor: "#4ade80",
      downColor: "#f0716a",
      wickUpColor: "#4ade80",
      wickDownColor: "#f0716a",
      borderVisible: false,
      priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
    });
    series.setData(candles as { time: Time; open: number; high: number; low: number; close: number }[]);
    const mkLine = (color: string, style: number) =>
      chart.addLineSeries({
        color,
        lineWidth: 1,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    mkLine("rgba(154,168,248,0.65)", 2).setData(bands.map((b) => ({ time: b.time as Time, value: b.upper })));
    mkLine("rgba(154,168,248,0.65)", 2).setData(bands.map((b) => ({ time: b.time as Time, value: b.lower })));
    mkLine("rgba(240,113,106,0.75)", 0).setData(bands.map((b) => ({ time: b.time as Time, value: b.mid })));
    if (markers?.length) series.setMarkers(markers);
    return () => chart.remove();
  }, [candles, bands, markers, digits]);

  const latest = candles[candles.length - 1];
  const summary = latest
    ? `${label}. ${candles.length} velas. Último cierre ${latest.close.toFixed(digits)}, máximo ${latest.high.toFixed(digits)}, mínimo ${latest.low.toFixed(digits)}.`
    : `${label}. Sin datos disponibles.`;

  return <div ref={ref} className={`chart${tall ? " tall" : ""}`} role="img" aria-label={summary} />;
}

export function AreaChart({
  data,
  color = "#9aa8f8",
  fit,
  label = "Gráfico de evolución",
}: {
  data: { time: number; value: number }[];
  color?: string;
  fit?: boolean;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = createChart(ref.current, CHART_OPTS);
    const series = chart.addAreaSeries({
      lineColor: color,
      lineWidth: 2,
      topColor: color + "40",
      bottomColor: color + "05",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    series.setData(data as { time: Time; value: number }[]);
    if (fit) chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, color, fit]);

  const values = data.map((point) => point.value);
  const summary = values.length
    ? `${label}. ${values.length} puntos. Último valor ${values[values.length - 1].toFixed(2)}, mínimo ${Math.min(...values).toFixed(2)}, máximo ${Math.max(...values).toFixed(2)}.`
    : `${label}. Sin datos disponibles.`;
  return <div ref={ref} className="chart" role="img" aria-label={summary} />;
}
