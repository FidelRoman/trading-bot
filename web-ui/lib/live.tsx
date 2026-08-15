"use client";
/* Contexto de datos en vivo: estado del bot + ticks de precio vía WebSocket,
   con polling de respaldo cada 15 s. Los eventos de vela/backtest incrementan
   contadores de versión para que las páginas refresquen sus datos. */

import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getJSON, wsProtocols, wsUrl } from "./api";
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
  syncError: string | null;
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
  syncError: null,
  refreshStatus: async () => {},
});

/** El backend emite tres tipos de mensaje: status, tick y backtest. */
type ServerMessage =
  | { type: "status"; status: Status }
  | { type: "tick"; prices: Prices; floating_pl: number; positions: Position[] }
  | { type: "backtest"; [key: string]: unknown };

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [prices, setPrices] = useState<Prices | null>(null);
  const [floatingPl, setFloatingPl] = useState(0);
  const [positions, setPositions] = useState<Position[]>([]);
  const [candleVersion, setCandleVersion] = useState(0);
  const [backtestVersion, setBacktestVersion] = useState(0);
  const [logVersion, setLogVersion] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  // El backend no emite un evento por vela: se deduce de last_candle, que sí
  // viaja en cada status. Un ref evita reabrir el socket al cambiar de vela.
  const lastCandle = useRef<string | null>(null);

  function applyStatus(next: Status) {
    setStatus(next);
    const candle = next.last_candle ?? null;
    if (candle !== lastCandle.current) {
      lastCandle.current = candle;
      setCandleVersion((value) => value + 1);
      setLogVersion((value) => value + 1);
    }
  }

  const refreshStatus = async () => {
    try {
      const next = await getJSON<Status>("/api/status");
      applyStatus(next);
      setSyncError(null);
    } catch (cause) {
      setSyncError("No se puede sincronizar con el backend. Se reintentará automáticamente.");
      throw cause;
    }
  };

  useEffect(() => {
    let alive = true;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        await refreshStatus();
        const open = await getJSON<Position[]>("/api/positions");
        if (!alive) return;
        setPositions(open);
        setFloatingPl(open.reduce((total, position) => total + (position.gross_pl ?? 0), 0));
      } catch {
        setSyncError("No se puede sincronizar con el backend. Se reintentará automáticamente.");
      }
    };

    function connect() {
      if (!alive) return;
      try {
        socket = new WebSocket(wsUrl(), wsProtocols());
      } catch {
        retry = setTimeout(connect, 5000);
        return;
      }

      socket.onopen = () => alive && setWsConnected(true);

      socket.onmessage = (event) => {
        if (!alive) return;
        let message: ServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type === "status") {
          applyStatus(message.status);
        } else if (message.type === "tick") {
          setPrices(message.prices);
          setPositions(message.positions ?? []);
          setFloatingPl(message.floating_pl ?? 0);
        } else if (message.type === "backtest") {
          setBacktestVersion((value) => value + 1);
        }
      };

      socket.onclose = () => {
        if (!alive) return;
        setWsConnected(false);
        // El cierre por token inválido (1008) también reintenta: AuthGate ya
        // habrá pedido credenciales nuevas para entonces.
        retry = setTimeout(connect, 5000);
      };

      socket.onerror = () => socket?.close();
    }

    poll();
    connect();
    const backup = setInterval(poll, 15000);

    return () => {
      alive = false;
      clearInterval(backup);
      if (retry) clearTimeout(retry);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
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
        syncError,
        refreshStatus,
      }}
    >
      {children}
    </LiveContext.Provider>
  );
}

export const useLive = () => useContext(LiveContext);
