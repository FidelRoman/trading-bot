"use client";

import { useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useLive } from "@/lib/live";

type Connection = "Demo" | "Real";

interface AccountState {
  connection: Connection;
  running: boolean;
  queued_commands: number;
}

export default function AccountCard() {
  const { status, refreshStatus } = useLive();
  const [account, setAccount] = useState<AccountState | null>(null);
  const [connection, setConnection] = useState<Connection>("Demo");
  const [acknowledgeReal, setAcknowledgeReal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  async function load() {
    const next = await getJSON<AccountState>("/api/account");
    setAccount(next);
    setConnection(next.connection);
  }

  useEffect(() => { load().catch(() => {}); }, [status?.connected, status?.mode]);

  async function save() {
    if (connection === "Real" && !acknowledgeReal) {
      setMessage({ text: "Confirma que operarás con dinero real.", ok: false });
      return;
    }
    setBusy(true);
    try {
      const result = await postJSON<{ ok: boolean; error?: string }>("/api/account", {
        connection,
        confirm_real: connection === "Real" && acknowledgeReal,
      });
      if (!result.ok) {
        setMessage({ text: result.error || "No se pudo cambiar la cuenta.", ok: false });
        return;
      }
      setMessage({ text: `Cuenta ${connection} seleccionada.`, ok: true });
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

  return (
    <section className="card narrow mb" aria-labelledby="account-title">
      <div className="card-head">
        <div className="card-title" id="account-title">CUENTA DE EJECUCIÓN</div>
        <span className={`chip ${real ? "real" : "ok"}`}>{real ? "CUENTA REAL" : "CUENTA DEMO"}</span>
      </div>

      {liveAccount?.account_id && (
        <p className="hint" style={{ marginBottom: 14 }}>
          Último estado: <b>{liveAccount.account_id}</b> · Balance ${fmt(liveAccount.balance)}
        </p>
      )}

      <div className="form-grid">
        <label>
          CUENTA FXCM
          <select
            value={connection}
            disabled={busy || !!account?.running}
            onChange={(event) => {
              const value = event.target.value as Connection;
              setConnection(value);
              if (value !== "Real") setAcknowledgeReal(false);
            }}
          >
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
            disabled={busy || !!account?.running}
            onChange={(event) => setAcknowledgeReal(event.target.checked)}
          />
          <span>Entiendo que las órdenes se enviarán a la cuenta Real seleccionada.</span>
        </label>
      )}

      <div className="form-actions">
        <button className="btn btn-start" disabled={busy || !!account?.running} onClick={save}>
          {busy ? "GUARDANDO…" : "SELECCIONAR CUENTA"}
        </button>
        {message && <span className={`hint ${message.ok ? "ok" : "err"}`}>{message.text}</span>}
      </div>

      <p className="hint" style={{ marginTop: 12 }}>
        Las credenciales viven exclusivamente en GitHub Secrets. Detén el bot antes de cambiar de cuenta.
        {account?.queued_commands ? ` Hay ${account.queued_commands} comando(s) en cola.` : ""}
      </p>
    </section>
  );
}
