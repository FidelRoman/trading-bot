"use client";

import { useEffect, useState } from "react";
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
}

interface SaveResult {
  ok: boolean;
  error?: string;
  connection?: string;
  is_real?: boolean;
  paused?: boolean;
}

export default function AccountCard() {
  const { status, refreshStatus } = useLive();
  const [saved, setSaved] = useState<CredentialsState | null>(null);
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [connection, setConnection] = useState<Connection>("auto");
  const [acknowledgeReal, setAcknowledgeReal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  async function load() {
    const next = await getJSON<CredentialsState>("/api/credentials");
    setSaved(next);
    setUser(next.user);
    setConnection(next.is_real ? "Real" : next.connected ? "Demo" : "auto");
  }

  useEffect(() => {
    load().catch(() => {});
  }, [status?.connected, status?.mode]);

  async function save() {
    if (connection === "Real" && !acknowledgeReal) {
      setMessage({ text: "Confirma que operarás con dinero real.", ok: false });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      // Contraseña vacía = conservar la que ya está en .env.
      const result = await postJSON<SaveResult>("/api/credentials", { user, password, connection });
      if (!result.ok) {
        setMessage({ text: result.error || "No se pudo conectar.", ok: false });
        return;
      }
      setPassword("");
      setMessage({
        text: result.is_real
          ? `Cuenta Real conectada.${result.paused ? " El bot ha quedado pausado." : ""}`
          : `Cuenta ${result.connection} conectada.`,
        ok: true,
      });
      await load();
      await refreshStatus();
    } catch {
      setMessage({ text: "No se pudo guardar la selección.", ok: false });
    } finally {
      setBusy(false);
    }
  }

  const liveAccount = status?.account;
  const real = connection === "Real";
  const running = !!status?.running;

  return (
    <section className="card narrow mb" aria-labelledby="account-title">
      <div className="card-head">
        <div className="card-title" id="account-title">CUENTA DE EJECUCIÓN</div>
        <span className={`chip ${saved?.is_real ? "real" : "ok"}`}>
          {saved?.is_real ? "CUENTA REAL" : saved?.connected ? "CUENTA DEMO" : "SIMULADO"}
        </span>
      </div>

      {liveAccount?.account_id && (
        <p className="hint" style={{ marginBottom: 14 }}>
          Último estado: <b>{liveAccount.account_id}</b> · Balance ${fmt(liveAccount.balance)}
        </p>
      )}

      <div className="form-grid">
        <label>
          USUARIO FXCM
          <input
            type="text"
            value={user}
            autoComplete="username"
            disabled={busy || running}
            onChange={(event) => setUser(event.target.value)}
          />
        </label>
        <label>
          CONTRASEÑA
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            placeholder={saved?.has_password ? "(guardada — dejar vacío para conservarla)" : ""}
            disabled={busy || running}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <label>
          CUENTA
          <select
            value={connection}
            disabled={busy || running}
            onChange={(event) => {
              const value = event.target.value as Connection;
              setConnection(value);
              if (value !== "Real") setAcknowledgeReal(false);
            }}
          >
            <option value="auto">Detectar (prueba Demo y luego Real)</option>
            <option value="Demo">Demo</option>
            <option value="Real">Real</option>
          </select>
        </label>
      </div>

      {real && (
        <label className="real-ack">
          <input
            type="checkbox"
            checked={acknowledgeReal}
            disabled={busy || running}
            onChange={(event) => setAcknowledgeReal(event.target.checked)}
          />
          <span>Entiendo que las órdenes se enviarán a la cuenta Real seleccionada.</span>
        </label>
      )}

      <div className="form-actions">
        <button className="btn btn-start" disabled={busy || running} onClick={save}>
          {busy ? "CONECTANDO…" : "CONECTAR CUENTA"}
        </button>
        {message && <span className={`hint ${message.ok ? "ok" : "err"}`}>{message.text}</span>}
      </div>

      <p className="hint" style={{ marginTop: 12 }}>
        Las credenciales se guardan en el <code>.env</code> de esta máquina y nunca salen de ella.
        Detén el bot antes de cambiar de cuenta. Si la cuenta resulta ser Real, el bot se pausa
        automáticamente.
      </p>
    </section>
  );
}
