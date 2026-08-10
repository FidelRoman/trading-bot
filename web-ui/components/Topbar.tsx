"use client";

import { clearApiToken, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { Status } from "@/lib/types";

export default function Topbar() {
  const { status, refreshStatus } = useLive();
  const isOn = !!status && !status.paused && !status.halted_today;
  const label = status?.halted_today ? "LÍMITE DIARIO" : status?.paused ? "PAUSADO" : "OPERANDO";

  async function setRunning(run: boolean) {
    await postJSON<{ ok: boolean; status: Status }>(`/api/control/${run ? "resume" : "pause"}`);
    await refreshStatus();
  }

  function logout() {
    clearApiToken();
    window.location.reload();
  }

  return (
    <header className="topbar">
      <h1 className="app-title">FX COMMAND CENTER</h1>
      <div className="top-actions">
        <span className={`pill${isOn ? "" : " paused"}`}>
          <span className="dot" />
          <span>{status ? label : "…"}</span>
        </span>
        <button className="btn btn-start" disabled={isOn} onClick={() => setRunning(true)}>
          INICIAR BOT
        </button>
        <button className="btn btn-stop" disabled={!isOn} onClick={() => setRunning(false)}>
          DETENER BOT
        </button>
        <button className="link-btn" onClick={logout} aria-label="Cerrar sesion del panel">
          SALIR
        </button>
      </div>
    </header>
  );
}
