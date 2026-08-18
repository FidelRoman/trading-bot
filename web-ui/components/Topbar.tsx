"use client";
/* La banda de estado: qué página, en qué cuenta, con qué instrumento, en qué
   estado el motor, y el mando para arrancarlo o pararlo. Antes esto vivía
   repartido entre cuatro indicadores que decían casi lo mismo. */

import { useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import ConfirmDialog from "./ConfirmDialog";
import Icon from "./ui/Icon";
import Mark from "./ui/Mark";
import ThemeToggle from "./ui/ThemeToggle";
import { useReach } from "./ui/reach";
import { useToast } from "./ui/Toast";
import { postJSON } from "@/lib/api";
import { readAccount, readEngine } from "@/lib/account";
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
  const { push } = useToast();
  const [pendingRun, setPendingRun] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const stopReach = useReach("engine");

  const account = readAccount(status);
  const engine = readEngine(status);
  const real = account.kind === "real";
  const pageTitle = PAGE_TITLES[pathname] ?? "Operación";

  const dialogCopy = useMemo(() => {
    if (pendingRun) {
      return real ? (
        <>
          El bot enviará órdenes a <strong>dinero real</strong> en{" "}
          {status?.instrument ?? "el instrumento seleccionado"}. Revisa estrategia, riesgo y
          posiciones antes de continuar.
        </>
      ) : (
        <>
          El bot comenzará a evaluar y ejecutar la estrategia en{" "}
          <strong>{account.label.toLowerCase()}</strong>.
        </>
      );
    }
    return (
      <>
        El bot dejará de abrir nuevas operaciones. Las posiciones existentes no se cerrarán
        automáticamente.
      </>
    );
  }, [pendingRun, real, status?.instrument, account.label]);

  async function setRunning(run: boolean) {
    setBusy(true);
    try {
      const result = await postJSON<{ ok: boolean; error?: string; status: Status }>(
        `/api/control/${run ? "resume" : "pause"}`,
        run && real ? { acknowledge_real: true } : {}
      );
      if (!result.ok) throw new Error(result.error || "No se pudo cambiar el estado del bot.");
      await refreshStatus();
      push(
        run ? "Bot iniciado." : "Bot detenido: no se abrirán nuevas operaciones.",
        run ? "ok" : "warn"
      );
      setPendingRun(null);
    } catch (cause) {
      push(
        cause instanceof Error ? cause.message : "No se pudo cambiar el estado del bot.",
        "danger"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <header className="band">
      <div className="band-title">
        <h1>{pageTitle}</h1>
      </div>

      <div className="band-readouts">
        {/* En móvil el raíl muestra la cuenta justo encima: no se repite. */}
        <div className="readout readout-account">
          <span className="readout-label">Cuenta</span>
          <span className="readout-value" style={{ fontSize: "var(--fs-sm)" }}>
            <Mark
              tone={
                account.tone === "danger" ? "danger" : account.tone === "info" ? "info" : "warn"
              }
            >
              {account.label}
            </Mark>
          </span>
        </div>
        <div className="readout">
          <span className="readout-label">Instrumento</span>
          <span className="readout-value">{status?.instrument ?? "—"}</span>
        </div>
        {/* Lo que «Detener bot» apaga: se resalta al apuntar al control. */}
        <div className="readout" data-reach-target="engine">
          <span className="readout-label">Motor</span>
          <span className="readout-value" style={{ fontSize: "var(--fs-sm)" }}>
            <Mark tone={engine.tone} dot live={engine.running}>
              {engine.label}
            </Mark>
          </span>
        </div>
      </div>

      <div className="band-actions">
        <button
          className="btn primary"
          disabled={!status || engine.running || busy}
          onClick={() => setPendingRun(true)}
        >
          <Icon name="play" size={13} />
          Iniciar bot
        </button>
        <button
          className="btn danger"
          disabled={!status || !engine.running || busy}
          onClick={() => setPendingRun(false)}
          {...stopReach}
        >
          <Icon name="pause" size={13} />
          Detener bot
        </button>
        <ThemeToggle />
      </div>

      <ConfirmDialog
        open={pendingRun !== null}
        title={pendingRun ? (real ? "Iniciar en cuenta real" : "Iniciar bot") : "Detener bot"}
        description={dialogCopy}
        consequence={pendingRun ? account.consequence : undefined}
        confirmLabel={pendingRun ? (real ? "Iniciar en real" : "Iniciar") : "Detener"}
        danger={real || pendingRun === false}
        busy={busy}
        onCancel={() => setPendingRun(null)}
        onConfirm={() => setRunning(Boolean(pendingRun))}
      />
    </header>
  );
}
