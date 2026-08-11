"use client";
/* Selector del instrumento que opera el bot: divisas, metales, materias primas,
   índices, acciones y CFD que la cuenta FXCM ofrece de verdad. El catálogo lo
   descubre el backend de la tabla OFFERS; aquí solo se lee y se elige. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { CatalogEntry, CurrentInstrument, InstrumentCatalog } from "@/lib/types";

const CLASS_LABELS: Record<string, string> = {
  forex: "Divisas",
  bullion: "Metales",
  commodity: "Materias primas",
  index: "Índices",
  treasury: "Deuda",
  crypto: "Cripto",
  share: "Acciones",
  other: "Otros",
};

const CLASS_ORDER = ["forex", "bullion", "commodity", "index", "treasury", "crypto", "share", "other"];

export default function InstrumentPicker({ onAction }: { onAction?: (msg: string, ok: boolean) => void }) {
  const { status, positions, refreshStatus } = useLive();
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [current, setCurrent] = useState<CurrentInstrument | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [truncated, setTruncated] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cat, cur] = await Promise.all([
        getJSON<InstrumentCatalog>("/api/instruments"),
        getJSON<CurrentInstrument>("/api/instrument"),
      ]);
      setCatalog(cat.instruments ?? []);
      setTruncated(Boolean(cat.truncated));
      setCurrent(cur);
    } catch {
      /* sin backend el selector se queda como esté */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, status?.instrument]);

  // El backend rechaza el cambio con posiciones abiertas: `open_trades()` filtra
  // por instrumento, así que cambiarlo dejaría una posición que el motor ya no
  // vería y nunca cerraría. Ese bloqueo se mantiene y hay que resolverlo a mano.
  const blocked = useMemo(
    () => (positions.length > 0
      ? `Cierra las ${positions.length === 1 ? "posición abierta" : `${positions.length} posiciones abiertas`} antes de cambiar de instrumento`
      : null),
    [positions.length]
  );
  // El bot en marcha también lo rechaza, pero eso sí se puede resolver aquí:
  // pausar es reversible de un clic, así que se ofrece en vez de mandar al
  // usuario a otro sitio y dejarle el selector muerto.
  const needsPause = !blocked && !!status?.running;

  const grouped = useMemo(() => {
    const needle = query.trim().toUpperCase();
    const filtered = needle
      ? catalog.filter((item) => item.symbol.toUpperCase().includes(needle))
      : catalog;
    const groups = new Map<string, CatalogEntry[]>();
    for (const item of filtered) {
      const key = CLASS_ORDER.includes(item.asset_class) ? item.asset_class : "other";
      const bucket = groups.get(key);
      if (bucket) bucket.push(item);
      else groups.set(key, [item]);
    }
    return CLASS_ORDER.filter((k) => groups.has(k)).map((k) => ({
      key: k,
      label: CLASS_LABELS[k] ?? k,
      items: groups.get(k)!,
    }));
  }, [catalog, query]);

  const symbol = current?.symbol ?? status?.instrument ?? "—";

  async function change(next: string) {
    if (!next || next === symbol) return;
    const entry = catalog.find((i) => i.symbol === next);

    if (needsPause) {
      const seguir = confirm(
        `El bot está en marcha y no se puede cambiar de instrumento operando.\n\n` +
          `¿Pausarlo y cambiar a ${next}?\n\n` +
          `Quedará pausado: para que vuelva a operar tendrás que darle a INICIAR.`
      );
      if (!seguir) return;
    }

    setBusy(true);
    try {
      if (needsPause) {
        const p = await postJSON<{ ok: boolean; error?: string }>("/api/control/pause");
        if (!p.ok) {
          onAction?.(`No se pudo pausar: ${p.error ?? "error desconocido"}`, false);
          return;
        }
        onAction?.("Bot pausado para cambiar de instrumento", true);
      }
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/instrument", { symbol: next });
      if (!r.ok) {
        onAction?.(`Error: ${r.error}`, false);
        return;
      }
      onAction?.(`Instrumento cambiado a ${next}`, true);
      if (entry && !entry.tradable) {
        // Suscribir modifica la cuenta FXCM de forma permanente: se pregunta.
        const activar = confirm(
          `${next} está en estado "${entry.subscription_status}" y no se puede operar.\n\n` +
            "¿Activarlo ahora? El cambio persiste en tu cuenta FXCM."
        );
        if (activar) {
          const s = await postJSON<{ ok: boolean; error?: string; status?: string }>(
            "/api/instrument/subscribe",
            { symbol: next }
          );
          onAction?.(s.ok ? `${next} activado (estado ${s.status})` : `Error: ${s.error}`, !!s.ok);
        }
      }
      await Promise.all([load(), refreshStatus()]);
    } finally {
      setBusy(false);
    }
  }

  async function refreshCatalog() {
    setBusy(true);
    try {
      const r = await postJSON<{ ok: boolean; error?: string; count?: number }>("/api/instruments/refresh");
      onAction?.(r.ok ? `Catálogo actualizado: ${r.count} instrumentos` : `Error: ${r.error}`, !!r.ok);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const modo = current?.execution_mode;
  const enVivo = modo === "live";

  return (
    <div className="card" style={{ marginBottom: "16px", padding: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
        <span style={{ fontSize: "12px", fontWeight: "bold", color: "var(--text-muted)", letterSpacing: "1px" }}>
          INSTRUMENTO
        </span>
        <button className="link-btn" onClick={refreshCatalog} disabled={busy}
                title="Volver a leer la tabla de ofertas de FXCM">
          ACTUALIZAR
        </button>
      </div>

      {modo && (
        <div
          style={{
            marginBottom: "10px", padding: "6px 10px", borderRadius: "6px", fontSize: "11px",
            fontWeight: 700, letterSpacing: "0.5px",
            background: enVivo ? "rgba(240,113,106,0.12)" : "rgba(154,168,248,0.10)",
            color: enVivo ? "#f0716a" : "var(--text-muted)",
            border: `1px solid ${enVivo ? "rgba(240,113,106,0.4)" : "var(--border)"}`,
          }}
        >
          {enVivo
            ? `ÓRDENES REALES — cuenta ${current?.connection}`
            : "SIMULADO — precios sintéticos"}
        </div>
      )}

      <input
        type="search"
        value={query}
        placeholder="Buscar (EUR, US30, AAPL…)"
        onChange={(e) => setQuery(e.target.value)}
        style={{
          width: "100%", marginBottom: "8px", background: "var(--card2)",
          border: "1px solid var(--border)", borderRadius: "6px",
          color: "var(--text)", fontSize: "13px", padding: "6px 10px", outline: "none",
        }}
      />

      {blocked && (
        <div className="picker-blocked">
          <strong>No se puede cambiar de instrumento.</strong> {blocked} — el bot
          filtra las operaciones abiertas por símbolo, así que al cambiar dejaría
          de verlas y no las cerraría nunca. Ciérralas en el panel de posiciones.
        </div>
      )}
      {needsPause && (
        <div className="picker-warn">
          El bot está operando: al elegir otro instrumento se pausará primero.
        </div>
      )}

      <select
        value={symbol}
        disabled={busy || !!blocked}
        onChange={(e) => change(e.target.value)}
        style={{
          width: "100%", background: "var(--card2)", border: "1px solid var(--border)",
          borderRadius: "6px", color: "var(--text)", fontSize: "13px",
          fontWeight: "600", padding: "6px 12px", outline: "none",
          cursor: blocked ? "not-allowed" : "pointer",
        }}
      >
        {/* El activo puede quedar fuera del filtro; se mantiene visible. */}
        {!grouped.some((g) => g.items.some((i) => i.symbol === symbol)) && (
          <option value={symbol}>{symbol}</option>
        )}
        {grouped.map((group) => (
          <optgroup key={group.key} label={group.label}>
            {group.items.map((item) => (
              <option key={item.symbol} value={item.symbol}>
                {item.symbol}
                {item.tradable ? "" : " — no operable"}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      <div style={{ marginTop: "8px", fontSize: "11px", color: "var(--text-muted)", lineHeight: 1.6 }}>
        {current && (
          <div>
            {CLASS_LABELS[current.asset_class] ?? current.asset_class} · pip {current.pip} ·
            mín {current.min_lot} · 1 lote = {current.lot_size} uds
          </div>
        )}
        {current && current.subscription_status !== "T" && (
          <div className="neg">Estado “{current.subscription_status}”: no operable todavía</div>
        )}
        {truncated && <div>Catálogo recortado: hay más instrumentos de los que caben</div>}
        {current?.catalog_updated_at
          ? <div>Catálogo: {current.catalog_updated_at.slice(0, 16).replace("T", " ")}</div>
          : <div>Catálogo sin descubrir — pulsa ACTUALIZAR</div>}
      </div>
    </div>
  );
}
