"use client";
/* Contexto de datos en vivo: estado del bot + ticks de precio vía WebSocket,
   con polling de respaldo cada 15 s. Los eventos de vela/backtest incrementan
   contadores de versión para que las páginas refresquen sus datos. */

import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getJSON, wsUrl } from "./api";
import type { Position, Prices, Status } from "./types";

interface LiveState {
  status: Status | null;
  prices: Prices | null;
  floatingPl: number;
  positions: Position[];
  candleVersion: number;
  backtestVersion: number;
  logVersion: number;
  wsConnected: boolean;
  refreshStatus: () => Promise<void>;
}

const LiveContext = createContext<LiveState>({
  status: null,
  prices: null,
  floatingPl: 0,
  positions: [],
  candleVersion: 0,
  backtestVersion: 0,
  logVersion: 0,
  wsConnected: false,
  refreshStatus: async () => {},
});

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [prices, setPrices] = useState<Prices | null>(null);
  const [floatingPl, setFloatingPl] = useState(0);
  const [positions, setPositions] = useState<Position[]>([]);
  const [candleVersion, setCandleVersion] = useState(0);
  const [backtestVersion, setBacktestVersion] = useState(0);
  const [logVersion, setLogVersion] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const refreshStatus = async () => {
    try {
      setStatus(await getJSON<Status>("/api/status"));
    } catch {
      /* backend caído: se reintenta en el siguiente ciclo */
    }
  };

  useEffect(() => {
    let alive = true;
    let reconnect: ReturnType<typeof setTimeout>;

    function connect() {
      if (!alive) return;
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      const ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "tick") {
          setPrices(msg.prices);
          setFloatingPl(msg.floating_pl ?? 0);
          if (msg.positions) setPositions(msg.positions);
        } else if (msg.type === "status") {
          setStatus(msg.status);
        } else if (msg.type === "candle") {
          setCandleVersion((v) => v + 1);
          setLogVersion((v) => v + 1);
        } else if (msg.type === "backtest") {
          setBacktestVersion((v) => v + 1);
          setLogVersion((v) => v + 1);
        }
      };
      ws.onclose = () => {
        clearInterval(ping);
        setWsConnected(false);
        reconnect = setTimeout(connect, 2000);
      };
    }

    connect();
    refreshStatus();
    getJSON<Position[]>("/api/positions").then(setPositions).catch(() => {});
    const poll = setInterval(refreshStatus, 15000);
    return () => {
      alive = false;
      clearTimeout(reconnect);
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, []);

  return (
    <LiveContext.Provider
      value={{
        status,
        prices,
        floatingPl,
        positions,
        candleVersion,
        backtestVersion,
        logVersion,
        wsConnected,
        refreshStatus,
      }}
    >
      {children}
    </LiveContext.Provider>
  );
}

export const useLive = () => useContext(LiveContext);
