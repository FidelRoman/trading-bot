"use client";
/* Selector del instrumento que opera el bot: divisas, metales, materias primas,
   índices, acciones y CFD que la cuenta FXCM ofrece de verdad. El catálogo lo
   descubre el backend de la tabla OFFERS; aquí solo se lee y se elige.

   Ya no es una tarjeta suelta: vive dentro del mandato, junto a la estrategia y
   el modelo, porque las tres cosas son la misma pregunta —qué opera el bot—. */

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import AssetBadge from "./ui/AssetBadge";
import ConfirmDialog from "./ConfirmDialog";
import Icon from "./ui/Icon";
import Notice from "./ui/Notice";
import { useReach } from "./ui/reach";
import { useToast } from "./ui/Toast";
import { getJSON, postJSON } from "@/lib/api";
import { getAssetBadgeInfo, getAssetCategory } from "@/lib/instruments";
import { useLive } from "@/lib/live";
import type { CatalogEntry, CurrentInstrument, InstrumentCatalog } from "@/lib/types";

const CLASS_LABELS: Record<string, string> = {
  forex: "Divisas (Forex)",
  bullion: "CFD Metales (Oro / Plata)",
  commodity: "CFD Materias primas (Petróleo / Gas)",
  index: "CFD Índices bursátiles (US30 / NAS100 / GER40)",
  treasury: "CFD Renta Fija / Bonos",
  crypto: "Criptomonedas (24/7)",
  share: "Acciones al contado (Stocks)",
  other: "Otros contratos",
};

const CLASS_ORDER = ["forex", "bullion", "commodity", "index", "treasury", "crypto", "share", "other"];

export default function InstrumentPicker() {
  const { status, positions, refreshStatus } = useLive();
  const { push } = useToast();
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [current, setCurrent] = useState<CurrentInstrument | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [pendingChange, setPendingChange] = useState<string | null>(null);
  const [pendingSubscription, setPendingSubscription] = useState<string | null>(null);
  const selectId = useId();
  const searchId = useId();
  const positionsReach = useReach("positions");

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
    () =>
      positions.length > 0
        ? `Cierra ${positions.length === 1 ? "la posición abierta" : `las ${positions.length} posiciones abiertas`} antes de cambiar de instrumento`
        : null,
    [positions.length]
  );
  // El bot en marcha también lo rechaza, pero eso sí se puede resolver aquí:
  // pausar es reversible de un clic, así que se ofrece en vez de mandar al
  // usuario a otro sitio y dejarle el selector muerto.
  // Con límite diario `running` se reporta false, pero el motor sigue armado;
  // solo `paused` confirma que es seguro cambiar de instrumento.
  const needsPause = !blocked && Boolean(status && !status.paused);

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

  async function change(next: string, pauseConfirmed = false) {
    if (!next || next === symbol) return;
    const entry = catalog.find((i) => i.symbol === next);

    if (needsPause && !pauseConfirmed) {
      setPendingChange(next);
      return;
    }

    setBusy(true);
    try {
      if (needsPause) {
        const p = await postJSON<{ ok: boolean; error?: string }>("/api/control/pause");
        if (!p.ok) {
          push(`No se pudo pausar: ${p.error ?? "error desconocido"}`, "danger");
          return;
        }
        push("Bot pausado para cambiar de instrumento.", "warn");
      }
      const r = await postJSON<{ ok: boolean; error?: string }>("/api/instrument", { symbol: next });
      if (!r.ok) {
        push(r.error ?? "No se pudo cambiar de instrumento.", "danger");
        return;
      }
      push(`Instrumento cambiado a ${next}.`);
      if (entry && !entry.tradable) setPendingSubscription(next);
      await Promise.all([load(), refreshStatus()]);
    } finally {
      setBusy(false);
    }
  }

  async function subscribe() {
    if (!pendingSubscription) return;
    setBusy(true);
    try {
      const s = await postJSON<{ ok: boolean; error?: string; status?: string }>(
        "/api/instrument/subscribe",
        { symbol: pendingSubscription }
      );
      push(
        s.ok
          ? `${pendingSubscription} activado (estado ${s.status}).`
          : (s.error ?? "No se pudo activar el instrumento."),
        s.ok ? "ok" : "danger"
      );
      if (s.ok) setPendingSubscription(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function refreshCatalog() {
    setBusy(true);
    try {
      const r = await postJSON<{ ok: boolean; error?: string; count?: number }>(
        "/api/instruments/refresh"
      );
      push(
        r.ok ? `Catálogo actualizado: ${r.count} instrumentos.` : (r.error ?? "No se pudo actualizar."),
        r.ok ? "ok" : "danger"
      );
      await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--s-2)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <label className="field-label" htmlFor={selectId}>
          Instrumento
        </label>
        <button
          className="btn quiet"
          onClick={refreshCatalog}
          disabled={busy}
          title="Volver a leer la tabla de ofertas de FXCM"
        >
          <Icon name="refresh" size={13} />
          Actualizar catálogo
        </button>
      </div>

      {blocked && (
        <div {...positionsReach}>
          <Notice tone="danger" title="No se puede cambiar de instrumento.">
            {blocked}: el bot filtra las operaciones abiertas por símbolo, así que al cambiar
            dejaría de verlas y no las cerraría nunca.
          </Notice>
        </div>
      )}
      {needsPause && (
        <Notice tone="warn">
          El bot está operando: al elegir otro instrumento se pausará primero.
        </Notice>
      )}

      <input
        id={searchId}
        className="input"
        aria-label="Buscar instrumento"
        type="search"
        value={query}
        placeholder="Buscar (EUR, US30, AAPL…)"
        onChange={(e) => setQuery(e.target.value)}
      />

      <select
        id={selectId}
        className="select"
        value={symbol}
        disabled={busy || !!blocked}
        onChange={(e) => change(e.target.value)}
      >
        {/* El activo puede quedar fuera del filtro; se mantiene visible. */}
        {!grouped.some((g) => g.items.some((i) => i.symbol === symbol)) && (
          <option value={symbol}>
            [{getAssetBadgeInfo(symbol, status?.asset_class).tag}] {symbol}
          </option>
        )}
        {grouped.map((group) => (
          <optgroup key={group.key} label={group.label}>
            {group.items.map((item) => {
              const info = getAssetBadgeInfo(item.symbol, item.asset_class);
              return (
                <option key={item.symbol} value={item.symbol}>
                  [{info.tag}] {item.symbol}
                  {item.tradable ? "" : " — no operable"}
                </option>
              );
            })}
          </optgroup>
        ))}
      </select>

      <div style={{ marginTop: "var(--s-1)", display: "flex", flexDirection: "column", gap: "var(--s-2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--s-2)", flexWrap: "wrap" }}>
          <AssetBadge
            symbol={symbol}
            assetClass={current?.asset_class ?? status?.asset_class}
            size="sm"
            showType={true}
          />
        </div>
        <div className="field-note">
          {current && (
            <div>
              {CLASS_LABELS[current.asset_class] ?? current.asset_class} · pip {current.pip} · mín{" "}
              {current.min_lot} · {current.asset_class === "share" ? "1 acción = 1 título" : current.asset_class === "forex" ? `1 lote = ${current.lot_size.toLocaleString()} uds` : `1 contrato CFD = ${current.lot_size} ud`}
            </div>
          )}
          {current && current.subscription_status !== "T" && (
            <div className="neg">Estado «{current.subscription_status}»: no operable todavía</div>
          )}
          {truncated && <div>Catálogo recortado: hay más instrumentos de los que caben</div>}
          {current?.catalog_updated_at ? (
            <div>Catálogo leído el {current.catalog_updated_at.slice(0, 16).replace("T", " ")}</div>
          ) : (
            <div>Catálogo sin descubrir — pulsa «Actualizar catálogo»</div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={pendingChange !== null}
        title="Pausar y cambiar instrumento"
        description={
          <>
            El bot se pausará antes de cambiar a <strong>{pendingChange}</strong>. Tendrás que
            iniciarlo de nuevo manualmente.
          </>
        }
        confirmLabel="Pausar y cambiar"
        busy={busy}
        onCancel={() => setPendingChange(null)}
        onConfirm={() => {
          const next = pendingChange;
          setPendingChange(null);
          if (next) void change(next, true);
        }}
      />
      <ConfirmDialog
        open={pendingSubscription !== null}
        title="Activar instrumento en FXCM"
        description={
          <>
            <strong>{pendingSubscription}</strong> no está habilitado para operar. Activarlo
            modificará de forma persistente la suscripción de la cuenta FXCM.
          </>
        }
        confirmLabel="Activar instrumento"
        danger
        busy={busy}
        onCancel={() => setPendingSubscription(null)}
        onConfirm={subscribe}
      />
    </div>
  );
}
