"use client";
/* Credenciales de la cuenta FXCM: edición, reconexión en caliente y
   detección automática de si la cuenta es DEMO o REAL. */

import { useEffect, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useLive } from "@/lib/live";

interface CredState {
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
  account_id?: string;
  balance?: number;
  paused?: boolean;
}

export default function AccountCard() {
  const { status, refreshStatus } = useLive();
  const [cred, setCred] = useState<CredState | null>(null);
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [connection, setConnection] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SaveResult | null>(null);

  async function load() {
    try {
      const c = await getJSON<CredState>("/api/credentials");
      setCred(c);
      setUser(c.user);
    } catch {
      /* backend caído */
    }
  }

  // Recargar cuando cambia la conexión/modo (p. ej. tras reconectar el backend)
  useEffect(() => { load(); }, [status?.connected, status?.mode]);

  async function save() {
    if (!user.trim()) { setResult({ ok: false, error: "Usuario obligatorio" }); return; }
    if (connection === "Real" || (cred?.is_real && connection === "auto")) {
      if (!confirm("⚠ Vas a conectar una cuenta que puede ser REAL (dinero real). ¿Continuar?")) return;
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await postJSON<SaveResult>("/api/credentials", {
        user: user.trim(),
        password,
        connection,
      });
      setResult(r);
      if (r.ok) {
        setPassword("");
        await load();
        await refreshStatus();
      }
    } catch (e) {
      setResult({ ok: false, error: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const modeBadge = !cred ? null : cred.mode === "simulado" ? (
    <span className="chip warn">SIMULADO</span>
  ) : cred.is_real ? (
    <span className="chip real">● CUENTA REAL</span>
  ) : (
    <span className="chip ok">CUENTA DEMO</span>
  );

  return (
    <div className="card narrow mb">
      <div className="card-head">
        <div className="card-title">🔐 CUENTA FXCM</div>
        <div style={{ display: "flex", gap: 8 }}>
          {modeBadge}
          <span className={`chip${cred?.connected ? " ok" : " warn"}`}>
            {cred?.connected ? "CONECTADO" : "SIN CONEXIÓN"}
          </span>
        </div>
      </div>

      {cred?.connected && cred.account_id && (
        <div className="hint" style={{ marginBottom: 14 }}>
          Cuenta <b>{cred.account_id}</b> · Balance ${fmt(cred.balance)} · Conexión {cred.connection}
        </div>
      )}

      <div className="form-grid">
        <label>
          USUARIO FXCM
          <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="D161666928" />
        </label>
        <label>
          CONTRASEÑA
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={cred?.has_password ? "•••••• (sin cambios)" : "contraseña"}
          />
        </label>
        <label>
          TIPO DE CUENTA
          <select value={connection} onChange={(e) => setConnection(e.target.value)}>
            <option value="auto">Detectar automáticamente</option>
            <option value="Demo">Demo (práctica)</option>
            <option value="Real">Real (dinero real)</option>
          </select>
        </label>
      </div>

      <div className="form-actions">
        <button className="btn btn-start" disabled={busy} onClick={save}>
          {busy ? "CONECTANDO…" : "GUARDAR Y CONECTAR"}
        </button>
        {result && !result.ok && <span className="hint err">✗ {result.error}</span>}
        {result?.ok && !result.is_real && (
          <span className="hint ok">
            ✓ Conectado — cuenta {result.connection} {result.account_id} (${fmt(result.balance)})
          </span>
        )}
      </div>

      {result?.ok && result.is_real && (
        <div className="bt-banner bad" style={{ marginTop: 14 }}>
          ⚠ CUENTA REAL detectada ({result.account_id}, ${fmt(result.balance)}). El bot quedó
          PAUSADO automáticamente: con dinero real solo debes activarlo tras validar la
          estrategia en demo durante semanas.
        </div>
      )}

      <div className="hint" style={{ marginTop: 12 }}>
        Las credenciales se guardan solo en el archivo local .env (fuera de git) y son las
        mismas que usas para conectar TradingView con FXCM. La contraseña nunca se muestra.
      </div>
    </div>
  );
}
