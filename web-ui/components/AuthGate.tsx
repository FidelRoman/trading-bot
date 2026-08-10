"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch, getApiToken, setApiToken } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = getApiToken();
    setToken(saved);
    if (saved) validate(saved);
  }, []);

  async function validate(value: string) {
    setApiToken(value);
    setChecking(true);
    setError("");
    try {
      const response = await apiFetch("/api/status");
      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "El token no es valido. Revisa BOT_API_TOKEN e intentalo de nuevo."
            : `El backend respondio ${response.status}. Revisa su configuracion.`
        );
      }
      setReady(true);
    } catch (cause) {
      setReady(false);
      setError(cause instanceof Error ? cause.message : "No se pudo conectar al backend.");
    } finally {
      setChecking(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = token.trim();
    if (!value) {
      setError("Introduce el token configurado en el backend.");
      return;
    }
    validate(value);
  }

  if (ready) return <>{children}</>;

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-mark" aria-hidden="true">FX</div>
        <p className="auth-kicker">ACCESO PROTEGIDO</p>
        <h1 id="auth-title">FX Command Center</h1>
        <p className="auth-copy">
          Introduce el token privado del backend. Se conserva solo durante esta sesion del navegador.
        </p>
        <form onSubmit={submit} className="auth-form">
          <label htmlFor="api-token">Token de acceso</label>
          <input
            id="api-token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            disabled={checking}
            autoFocus
          />
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="btn btn-start auth-submit" type="submit" disabled={checking}>
            {checking ? "VERIFICANDO..." : "ENTRAR"}
          </button>
        </form>
      </section>
    </main>
  );
}
