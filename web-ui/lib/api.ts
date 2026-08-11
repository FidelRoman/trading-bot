const TOKEN_KEY = "tradingbot_api_token";

export function getApiToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setApiToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearApiToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getApiToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

export async function getJSON<T>(url: string): Promise<T> {
  const r = await apiFetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

export async function postJSON<T = { ok: boolean; error?: string }>(
  url: string,
  body?: unknown
): Promise<T> {
  const r = await apiFetch(url, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

/** En producción la UI la sirve el propio backend, así que el WebSocket vive en
 *  el mismo origen y atraviesa el túnel sin configuración extra. En `next dev`
 *  el frontend está en otro puerto: NEXT_PUBLIC_BACKEND_PORT apunta al backend. */
export function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT;
  return port
    ? `${proto}://${window.location.hostname}:${port}/ws`
    : `${proto}://${window.location.host}/ws`;
}

export function wsProtocols(): string[] {
  const token = getApiToken();
  return token ? ["bearer", token] : ["bearer"];
}
