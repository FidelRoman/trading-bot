"use client";
/* La tabla de la lámina: cabecera fija, filetes, numéricos a la derecha con
   cifras tabulares, y orden por columna donde tiene sentido. */

import React, { useMemo, useState } from "react";
import Icon from "./Icon";

export function TableFrame({
  children,
  maxHeight,
}: {
  children: React.ReactNode;
  maxHeight?: number;
}) {
  return (
    <div
      className="table-frame"
      style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}
      tabIndex={0}
      role="region"
      aria-label="Tabla desplazable"
    >
      {children}
    </div>
  );
}

export type SortDirection = "asc" | "desc";

/** Orden por columna para tablas de datos. `key` es cualquier identificador. */
export function useSort<T extends string>(initial: T, initialDirection: SortDirection = "desc") {
  const [key, setKey] = useState<T>(initial);
  const [direction, setDirection] = useState<SortDirection>(initialDirection);

  const toggle = (next: T) => {
    if (next === key) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setKey(next);
      setDirection("desc");
    }
  };

  const compare = useMemo(
    () =>
      (a: number | string | null | undefined, b: number | string | null | undefined): number => {
        const factor = direction === "asc" ? 1 : -1;
        if (a == null && b == null) return 0;
        if (a == null) return 1;
        if (b == null) return -1;
        if (typeof a === "number" && typeof b === "number") return (a - b) * factor;
        return String(a).localeCompare(String(b), "es") * factor;
      },
    [direction]
  );

  return { key, direction, toggle, compare };
}

export function SortHeader<T extends string>({
  column,
  sort,
  numeric,
  children,
  title,
}: {
  column: T;
  sort: { key: T; direction: SortDirection; toggle: (key: T) => void };
  numeric?: boolean;
  children: React.ReactNode;
  title?: string;
}) {
  const active = sort.key === column;
  return (
    <th
      className={numeric ? "num" : undefined}
      title={title}
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => sort.toggle(column)}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "inline-flex",
          gap: 4,
          alignItems: "center",
          color: active ? "var(--ink)" : "inherit",
        }}
      >
        {children}
        <span style={{ opacity: active ? 1 : 0.3, display: "inline-flex" }}>
          <Icon name={active && sort.direction === "asc" ? "sortAsc" : "sortDesc"} size={12} />
        </span>
      </button>
    </th>
  );
}
