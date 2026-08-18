"use client";

import { useEffect, useId, useState } from "react";
import Mark from "./ui/Mark";
import Notice from "./ui/Notice";
import { Panel } from "./ui/Panel";
import { useReach } from "./ui/reach";
import { useToast } from "./ui/Toast";
import { getJSON, postJSON } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useLive } from "@/lib/live";

type Connection = "auto" | "Demo" | "Real";

/** Lo que devuelve GET /api/credentials. Nunca incluye la contraseña. */
interface CredentialsState {
  user: string;
  has_password: boolean;
  connection: string;
  mode: string;
  connected: boolean;
  is_real: boolean;
  account_id?: string | null;
  balance?: number | null;
  has_demo?: boolean;
  has_real?: boolean;
}

interface SaveResult {
  ok: boolean;
  error?: string;
  connection?: string;
  is_real?: boolean;
  paused?: boolean;
}

export default function AccountCard() {
  const { status, positions, refreshStatus } = useLive();
  const { push } = useToast();
  const [saved, setSaved] = useState<CredentialsState | null>(null);
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [connection, setConnection] = useState<Connection>("auto");
  const [acknowledgeReal, setAcknowledgeReal] = useState(false);
  const [busy, setBusy] = useState(false);
  const userId = useId();
  const passId = useId();
  const connId = useId();
  const positionsReach = useReach("positions");

  async function load() {
    const next = await getJSON<CredentialsState>("/api/credentials");
    setSaved(next);
    setUser(next.user);
    setConnection(
      next.connection === "Real" || next.connection === "Demo" ? next.connection : "auto"
    );
  }

  useEffect(() => {
    load().catch(() => push("No se pudo cargar el estado de la cuenta.", "danger"));
  }, [status?.connected, status?.mode]);

  async function save() {
    if (connection === "Real" && !acknowledgeReal) {
      push("Confirma que operarás con dinero real.", "warn");
      return;
    }
    setBusy(true);
    try {
      // Contraseña vacía = conservar la que ya está en .env.
      const result = await postJSON<SaveResult>("/api/credentials", {
        user,
        password,
        connection,
        acknowledge_real: connection === "Real" && acknowledgeReal,
      });
      if (!result.ok) {
        push(result.error || "No se pudo conectar.", "danger");
        return;
      }
      setPassword("");
      push(
        result.is_real
          ? `Cuenta real conectada.${result.paused ? " El bot ha quedado pausado." : ""}`
          : `Cuenta ${result.connection} conectada.`,
        result.is_real ? "warn" : "ok"
      );
      await load();
      await refreshStatus();
    } catch {
      push("No se pudo guardar la selección.", "danger");
    } finally {
      setBusy(false);
    }
  }

  const liveAccount = status?.account;
  const real = connection === "Real";
  // `running` puede ser false por límite diario aunque el motor siga armado.
  // `paused` es la fuente de verdad para permitir cambios de cuenta.
  const running = Boolean(status && !status.paused);
  const hasOpenPositions = positions.length > 0;
  const blocked = !status || running || hasOpenPositions;

  return (
    <Panel
      label="Cuenta y credenciales"
      actions={
        <Mark tone={saved?.is_real ? "danger" : saved?.connected ? "info" : "warn"}>
          {saved?.is_real ? "Cuenta real" : saved?.connected ? "Cuenta demo" : "Simulado"}
        </Mark>
      }
      caption={
        <>
          Las credenciales se guardan en el <code>.env</code> de esta máquina y nunca salen de
          ella. Si la cuenta resulta ser real, el bot se pausa automáticamente al conectar.
        </>
      }
    >
      <div style={{ display: "grid", gap: "var(--s-4)" }}>
        <div className="field-note">
          Credenciales guardadas: demo {saved?.has_demo ? "sí" : "no"} · real{" "}
          {saved?.has_real ? "sí" : "no"}
          {liveAccount?.account_id && (
            <>
              {" "}
              · último estado {liveAccount.account_id}, balance{" "}
              <span className="num">${fmt(liveAccount.balance)}</span>
            </>
          )}
        </div>

        {blocked && (
          <div {...(hasOpenPositions ? positionsReach : {})}>
            <Notice tone="warn" title="Los cambios de cuenta están bloqueados.">
              {!status
                ? "Esperando el estado del bot."
                : running
                  ? "Detén el bot antes de cambiar de cuenta o de credenciales."
                  : `Cierra ${positions.length === 1 ? "la posición abierta" : `las ${positions.length} posiciones abiertas`} antes de cambiar de cuenta.`}
            </Notice>
          </div>
        )}

        <div className="field-grid">
          <div className="field">
            <label className="field-label" htmlFor={userId}>
              Usuario FXCM
            </label>
            <input
              id={userId}
              className="input"
              type="text"
              value={user}
              autoComplete="username"
              disabled={busy || blocked}
              onChange={(event) => setUser(event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={passId}>
              Contraseña
            </label>
            <input
              id={passId}
              className="input"
              type="password"
              value={password}
              autoComplete="current-password"
              placeholder={saved?.has_password ? "Guardada — vacío la conserva" : ""}
              disabled={busy || blocked}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={connId}>
              Cuenta
            </label>
            <select
              id={connId}
              className="select"
              value={connection}
              disabled={busy || blocked}
              onChange={(event) => {
                const value = event.target.value as Connection;
                setConnection(value);
                if (value !== "Real") setAcknowledgeReal(false);
              }}
            >
              <option value="auto">Detectar (prueba demo y luego real)</option>
              <option value="Demo">Demo</option>
              <option value="Real">Real</option>
            </select>
          </div>
        </div>

        {real && (
          <label
            style={{
              display: "flex",
              gap: "var(--s-2)",
              alignItems: "flex-start",
              padding: "var(--s-3)",
              border: "1px solid var(--short)",
              background: "var(--short-wash)",
              fontSize: "var(--fs-2xs)",
              lineHeight: "var(--lh-body)",
            }}
          >
            <input
              type="checkbox"
              checked={acknowledgeReal}
              disabled={busy || blocked}
              onChange={(event) => setAcknowledgeReal(event.target.checked)}
              style={{ width: 15, height: 15, flex: "0 0 auto", accentColor: "var(--short)" }}
            />
            <span>Entiendo que las órdenes se enviarán a la cuenta real seleccionada.</span>
          </label>
        )}

        <div>
          <button className="btn primary" disabled={busy || blocked} onClick={save}>
            {busy ? "Conectando…" : "Conectar cuenta"}
          </button>
        </div>
      </div>
    </Panel>
  );
}
