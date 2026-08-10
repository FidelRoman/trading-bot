"use client";
/* Contexto de datos en vivo: estado del bot + ticks de precio vía WebSocket,
   con polling de respaldo cada 15 s. Los eventos de vela/backtest incrementan
   contadores de versión para que las páginas refresquen sus datos. */

import React, { createContext, useContext, useEffect, useState } from "react";
import { getJSON } from "./api";
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

  const refreshStatus = async () => {
    try {
      const snapshot = await getJSON<{
        status: Status;
        prices: Prices | null;
        positions: Position[];
      }>("/api/snapshot");
      setStatus(snapshot.status);
      setPrices(snapshot.prices);
      setPositions(snapshot.positions ?? []);
      setFloatingPl(
        (snapshot.positions ?? []).reduce((total, position) => total + (position.gross_pl ?? 0), 0)
      );
      setWsConnected(true);
    } catch {
      /* backend caído: se reintenta en el siguiente ciclo */
      setWsConnected(false);
    }
  };

  useEffect(() => {
    let alive = true;
    refreshStatus();
    getJSON<Position[]>("/api/positions").then(setPositions).catch(() => {});
    const poll = setInterval(() => {
      refreshStatus().then(() => {
        if (alive) {
          setCandleVersion((value) => value + 1);
          setLogVersion((value) => value + 1);
        }
      });
    }, 60000);
    return () => {
      alive = false;
      clearInterval(poll);
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
