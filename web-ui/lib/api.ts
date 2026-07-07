export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

export async function postJSON<T = { ok: boolean; error?: string }>(
  url: string,
  body?: unknown
): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export function wsUrl(): string {
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT ?? "8000";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:${port}/ws`;
}
