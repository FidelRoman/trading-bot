"use client";

import { useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import ConfirmDialog from "./ConfirmDialog";
import { clearApiToken, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { Status } from "@/lib/types";

const PAGE_TITLES: Record<string, string> = {
  "/": "Operación",
  "/fsr": "Señal FSR",
  "/train": "Entrenamiento",
  "/models": "Modelos",
  "/strategies": "Estrategias y simulación",
  "/settings": "Ajustes",
  "/history": "Historial",
  "/activity": "Actividad",
};

export default function Topbar() {
  const { status, refreshStatus } = useLive();
  const pathname = usePathname();
  const [pendingRun, setPendingRun] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const isOn = !!status && !status.paused;
  const label = status?.halted_today ? "LÍMITE DIARIO" : status?.paused ? "PAUSADO" : "OPERANDO";
  const connection = status?.account?.connection ?? "";
  const real = Boolean(status?.live_execution && (connection === "Real" || status?.mode.includes("real")));
  const demo = Boolean(status?.live_execution && !real);
  const accountLabel = real ? "CUENTA REAL" : demo ? "CUENTA DEMO" : "SIMULADO";
  const accountTone = real ? "real" : demo ? "demo" : "sim";
  const pageTitle = PAGE_TITLES[pathname] ?? "FX Command Center";
  const dialogCopy = useMemo(() => {
    if (pendingRun) {
      return real
        ? <>El bot enviará órdenes a <strong>dinero real</strong> en {status?.instrument ?? "el instrumento seleccionado"}. Revisa estrategia, riesgo y posiciones antes de continuar.</>
        : <>El bot comenzará a evaluar y ejecutar la estrategia en <strong>{accountLabel.toLowerCase()}</strong>.</>;
    }
    return <>El bot dejará de abrir nuevas operaciones. Las posiciones existentes no se cerrarán automáticamente.</>;
  }, [pendingRun, real, status?.instrument, accountLabel]);

  async function setRunning(run: boolean) {
    setBusy(true);
    setMessage("");
    try {
      const result = await postJSON<{ ok: boolean; error?: string; status: Status }>(
        `/api/control/${run ? "resume" : "pause"}`,
        run && real ? { acknowledge_real: true } : {}
      );
      if (!result.ok) throw new Error(result.error || "No se pudo cambiar el estado del bot.");
      await refreshStatus();
      setMessage(run ? "Bot iniciado." : "Bot detenido: no se abrirán nuevas operaciones.");
      setPendingRun(null);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "No se pudo cambiar el estado del bot.");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearApiToken();
    window.location.reload();
  }

  return (
    <header className="topbar">
      <div className="topbar-heading">
        <span className="topbar-kicker">FX COMMAND CENTER</span>
        <h1 className="app-title">{pageTitle}</h1>
      </div>
      <div className="top-actions">
        <span className={`account-pill ${accountTone}`}>
          <span>{accountLabel}</span>
          <strong>{status?.instrument ?? "—"}</strong>
        </span>
        <span className={`pill${isOn && !status?.halted_today ? "" : " paused"}`} role="status" aria-live="polite">
          <span className="dot" />
          <span>{status ? label : "…"}</span>
        </span>
        <button className="btn btn-start" disabled={!status || isOn || busy} onClick={() => setPendingRun(true)}>
          INICIAR BOT
        </button>
        <button className="btn btn-stop" disabled={!status || !isOn || busy} onClick={() => setPendingRun(false)}>
          DETENER BOT
        </button>
        <button className="link-btn" onClick={logout} aria-label="Cerrar sesion del panel">
          SALIR
        </button>
      </div>
      {message && <div className="topbar-message" role="status" aria-live="polite">{message}</div>}
      <ConfirmDialog
        open={pendingRun !== null}
        title={pendingRun ? (real ? "Iniciar en cuenta Real" : "Iniciar bot") : "Detener bot"}
        description={dialogCopy}
        confirmLabel={pendingRun ? (real ? "INICIAR EN REAL" : "INICIAR") : "DETENER"}
        danger={real || pendingRun === false}
        busy={busy}
        onCancel={() => setPendingRun(null)}
        onConfirm={() => setRunning(Boolean(pendingRun))}
      />
    </header>
  );
}
