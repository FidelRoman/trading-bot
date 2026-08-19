"use client";
/* OPERACIÓN — la lámina principal.

   La figura del instrumento manda la primera pantalla, con su titular (el
   precio vivo) y su pie de ejes. A la derecha, el mandato: qué opera el bot,
   qué tiene abierto y qué ha ido anotando. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { CandleChart } from "@/components/charts";
import FsrppoPanel from "@/components/FsrppoPanel";
import LogsPanel from "@/components/LogsPanel";
import Mandate from "@/components/Mandate";
import PositionsPanel from "@/components/PositionsPanel";
import StrategyControls from "@/components/StrategyControls";
import AssetBadge from "@/components/ui/AssetBadge";
import Mark from "@/components/ui/Mark";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import Skeleton from "@/components/ui/Skeleton";
import { getJSON } from "@/lib/api";
import { fmt, signedMoney } from "@/lib/format";
import { formatDistanceByAsset, formatPriceByAsset } from "@/lib/instruments";
import { useLive } from "@/lib/live";
import type { Band, Candle, Trade } from "@/lib/types";

const TIMEFRAMES = ["m5", "m15", "h1", "h4", "d1"] as const;

export default function Operacion() {
  const { status, prices, floatingPl, candleVersion, wsConnected } = useLive();
  // Decimales e instrumento vienen del status: la UI no asume EUR/USD.
  const digits = status?.digits ?? 5;
  const symbol = status?.instrument ?? "—";
  const [tf, setTf] = useState<string>("m15");
  const [candles, setCandles] = useState<Candle[] | null>(null);
  const [bands, setBands] = useState<Band[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [dataError, setDataError] = useState("");

  const activeStrategy = status?.active_strategy || "bollinger";

  // El precio sube o baja respecto al tick anterior: la tinta lo dice.
  const previous = useRef<number | null>(null);
  const [drift, setDrift] = useState<"pos" | "neg" | null>(null);
  useEffect(() => {
    const bid = prices?.bid;
    if (bid == null) return;
    if (previous.current != null && bid !== previous.current) {
      setDrift(bid > previous.current ? "pos" : "neg");
    }
    previous.current = bid;
  }, [prices?.bid]);

  useEffect(() => {
    let alive = true;
    setDataError("");
    setCandles(null);
    getJSON<{ candles: Candle[]; bands: Band[] }>(`/api/candles?count=200&tf=${tf}`)
      .then((d) => {
        if (alive) {
          setCandles(d.candles);
          setBands(d.bands);
        }
      })
      .catch(
        () =>
          alive &&
          setDataError("No se pudo cargar el gráfico. Comprueba la conexión e inténtalo de nuevo.")
      );
    getJSON<Trade[]>("/api/trades?limit=100")
      .then((t) => alive && setTrades(t))
      .catch(() => alive && setDataError("No se pudieron cargar todos los datos de operación."));
    return () => {
      alive = false;
    };
  }, [tf, candleVersion, activeStrategy]);

  const markers = useMemo<SeriesMarker<Time>[]>(() => {
    if (tf !== "m15") return [];
    return trades
      .filter((t) => t.entry_time)
      .map((t) => ({
        time: (Math.floor(new Date(t.entry_time!).getTime() / 1000 / 900) * 900) as Time,
        position: t.side === "long" ? ("belowBar" as const) : ("aboveBar" as const),
        color: t.side === "long" ? "var(--long)" : "var(--short)",
        shape: t.side === "long" ? ("arrowUp" as const) : ("arrowDown" as const),
        text: t.side === "long" ? "C" : "V",
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));
  }, [trades, tf]);

  return (
    <div className="plate split">
      <div className="stack">
        <section className="panel" aria-label={`Cotización de ${symbol}`}>
          <div className="panel-head" style={{ flexWrap: "wrap", gap: "var(--s-4)" }}>
            <div className="lede" style={{ alignItems: "center" }}>
              <AssetBadge
                symbol={symbol}
                assetClass={status?.asset_class}
                size="lg"
                showType={true}
              />
              <span className={`lede-price num${drift ? ` ${drift}` : ""}`}>
                {formatPriceByAsset(prices?.bid, symbol, status?.asset_class, digits)}
              </span>
              <Mark tone={wsConnected ? "ok" : "warn"} dot live={wsConnected}>
                {wsConnected ? "En vivo" : "Reconectando"}
              </Mark>
            </div>
            <div className="panel-actions">
              <div className="seg" role="group" aria-label="Temporalidad del gráfico">
                {TIMEFRAMES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={tf === t}
                    aria-label={`Mostrar velas de ${t.toUpperCase()}`}
                    onClick={() => setTf(t)}
                  >
                    {t.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {status?.market_open === false && !status?.connected && (
            <div style={{ padding: "var(--s-3) var(--s-4) 0" }}>
              <Notice tone="info" title="Mercado cerrado.">
                {status.market_status} El bot reanudará la conexión automáticamente al abrir el
                mercado.
              </Notice>
            </div>
          )}
          {dataError && (
            <div style={{ padding: "var(--s-3) var(--s-4) 0" }}>
              <Notice tone="danger">{dataError}</Notice>
            </div>
          )}

          <div className="panel-body bleed" style={{ padding: "var(--s-3) var(--s-2) 0" }}>
            {candles === null ? (
              <div className="figure tall" style={{ display: "grid", placeItems: "center" }}>
                <Skeleton height="100%" />
              </div>
            ) : (
              <CandleChart
                candles={candles}
                bands={bands}
                markers={markers}
                digits={digits}
                label={`Gráfico de velas de ${symbol} en ${tf.toUpperCase()}`}
                tall
              />
            )}
          </div>

          <div className="axis-foot">
            <span>
              Compra <b className="num">{formatPriceByAsset(prices?.bid, symbol, status?.asset_class, digits)}</b>
            </span>
            <span>
              Venta <b className="num">{formatPriceByAsset(prices?.ask, symbol, status?.asset_class, digits)}</b>
            </span>
            <span>
              Spread <b className="num">{fmt(prices?.spread_pips, 1)}</b>{" "}
              {status?.asset_class === "share" ? "spread" : status?.asset_class === "index" ? "pts" : "pips"}
            </span>
            <span>
              P&L flotante{" "}
              <b className={`num ${floatingPl >= 0 ? "pos" : "neg"}`}>{signedMoney(floatingPl)}</b>
            </span>
          </div>
        </section>

        <FsrppoPanel />
        <StrategyControls />
      </div>

      <div className="stack">
        <Mandate />
        <PositionsPanel />
        <Panel label="Registro del sistema" bleed>
          <div style={{ padding: "var(--s-3) var(--s-4)" }}>
            <LogsPanel />
          </div>
        </Panel>
      </div>
    </div>
  );
}
