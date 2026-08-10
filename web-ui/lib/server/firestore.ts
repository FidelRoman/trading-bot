import { createSign } from "node:crypto";

type ServiceAccount = {
  client_email: string;
  private_key: string;
  project_id: string;
};

type FirestoreValue = {
  nullValue?: null;
  booleanValue?: boolean;
  integerValue?: string;
  doubleValue?: number | string;
  timestampValue?: string;
  stringValue?: string;
  arrayValue?: { values?: FirestoreValue[] };
  mapValue?: { fields?: Record<string, FirestoreValue> };
};

type FirestoreDocument = {
  name: string;
  fields?: Record<string, FirestoreValue>;
};

let cachedToken: { value: string; expiresAt: number } | null = null;

function serviceAccount(): ServiceAccount {
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON no configurado");
  return JSON.parse(raw) as ServiceAccount;
}

function base64url(value: string | Buffer): string {
  return Buffer.from(value).toString("base64url");
}

async function accessToken(): Promise<string> {
  if (cachedToken && cachedToken.expiresAt > Date.now() + 60_000) return cachedToken.value;

  const account = serviceAccount();
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = base64url(JSON.stringify({
    iss: account.client_email,
    scope: "https://www.googleapis.com/auth/datastore",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  }));
  const unsigned = `${header}.${claims}`;
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  signer.end();
  const assertion = `${unsigned}.${base64url(signer.sign(account.private_key))}`;

  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }),
  });
  if (!response.ok) throw new Error(`No se pudo autenticar Firestore (${response.status})`);
  const result = await response.json() as { access_token: string; expires_in: number };
  cachedToken = { value: result.access_token, expiresAt: Date.now() + result.expires_in * 1000 };
  return cachedToken.value;
}

function encode(value: unknown): FirestoreValue {
  if (value === null || value === undefined) return { nullValue: null };
  if (typeof value === "boolean") return { booleanValue: value };
  if (typeof value === "number") {
    return Number.isInteger(value) ? { integerValue: String(value) } : { doubleValue: value };
  }
  if (typeof value === "string") return { stringValue: value };
  if (Array.isArray(value)) return { arrayValue: { values: value.map(encode) } };
  const fields = Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, encode(item)]),
  );
  return { mapValue: { fields } };
}

function decode(value: FirestoreValue): unknown {
  if ("nullValue" in value) return null;
  if (value.booleanValue !== undefined) return value.booleanValue;
  if (value.integerValue !== undefined) return Number(value.integerValue);
  if (value.doubleValue !== undefined) return Number(value.doubleValue);
  if (value.timestampValue !== undefined) return value.timestampValue;
  if (value.stringValue !== undefined) return value.stringValue;
  if (value.arrayValue !== undefined) return (value.arrayValue.values || []).map(decode);
  if (value.mapValue !== undefined) return decodeFields(value.mapValue.fields || {});
  return null;
}

function decodeFields(fields: Record<string, FirestoreValue>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, decode(value)]));
}

function projectId(): string {
  return process.env.FIRESTORE_PROJECT_ID || serviceAccount().project_id;
}

function prefix(): string {
  return process.env.FIRESTORE_COLLECTION_PREFIX || "tradingbot";
}

function documentUrl(collection: string, document = ""): string {
  const root = `https://firestore.googleapis.com/v1/projects/${encodeURIComponent(projectId())}/databases/(default)/documents`;
  return `${root}/${encodeURIComponent(collection)}${document ? `/${encodeURIComponent(document)}` : ""}`;
}

async function firestoreFetch(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, {
    ...init,
    headers: { Authorization: `Bearer ${await accessToken()}`, "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Firestore respondio ${response.status}`);
  }
  return response;
}

export async function getState<T>(key: string, fallback: T): Promise<T> {
  const response = await firestoreFetch(documentUrl(`${prefix()}_state`, key));
  if (response.status === 404) return fallback;
  const document = await response.json() as FirestoreDocument;
  return (decode(document.fields?.value || { nullValue: null }) as T) ?? fallback;
}

export async function setState(key: string, value: unknown): Promise<void> {
  await firestoreFetch(documentUrl(`${prefix()}_state`, key), {
    method: "PATCH",
    body: JSON.stringify({
      fields: {
        value: encode(value),
        updated_at: { timestampValue: new Date().toISOString() },
      },
    }),
  });
}

export async function setCollectionDocument(
  name: string,
  id: string,
  value: Record<string, unknown>,
): Promise<void> {
  await firestoreFetch(documentUrl(`${prefix()}_${name}`, id), {
    method: "PATCH",
    body: JSON.stringify({
      fields: Object.fromEntries(Object.entries(value).map(([key, item]) => [key, encode(item)])),
    }),
  });
}

export async function collectionRows(name: string): Promise<Record<string, unknown>[]> {
  const rows: Record<string, unknown>[] = [];
  let pageToken = "";
  do {
    const url = new URL(documentUrl(`${prefix()}_${name}`));
    url.searchParams.set("pageSize", "1000");
    if (pageToken) url.searchParams.set("pageToken", pageToken);
    const response = await firestoreFetch(url.toString());
    if (response.status === 404) return rows;
    const result = await response.json() as { documents?: FirestoreDocument[]; nextPageToken?: string };
    for (const document of result.documents || []) {
      rows.push({ id: document.name.split("/").pop(), ...decodeFields(document.fields || {}) });
    }
    pageToken = result.nextPageToken || "";
  } while (pageToken);
  return rows;
}
