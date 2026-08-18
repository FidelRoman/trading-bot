"use client";
/* El bloque de figura de la lámina: filete, rótulo, cuerpo y pie.
   El pie es donde vive la prosa explicativa que antes andaba suelta en `hint`. */

import type React from "react";

export function Panel({
  label,
  count,
  actions,
  caption,
  bleed,
  tight,
  labelledBy,
  as: Tag = "section",
  headingLevel = 2,
  className = "",
  bodyClassName = "",
  children,
}: {
  /** Rótulo del panel. Se compone como encabezado real salvo que no lleve. */
  label?: React.ReactNode;
  /** Cifra secundaria junto al rótulo (nº de posiciones, de modelos…). */
  count?: React.ReactNode;
  actions?: React.ReactNode;
  /** Pie de figura: la explicación, con medida de lectura. */
  caption?: React.ReactNode;
  /** Cuerpo sin relleno: para tablas y gráficos a sangre. */
  bleed?: boolean;
  tight?: boolean;
  labelledBy?: string;
  as?: "section" | "div" | "article";
  headingLevel?: 2 | 3;
  className?: string;
  bodyClassName?: string;
  children?: React.ReactNode;
}) {
  const Heading = (headingLevel === 3 ? "h3" : "h2") as "h2" | "h3";
  const headingId = labelledBy ?? (typeof label === "string" ? slug(label) : undefined);

  return (
    <Tag className={`panel ${className}`} aria-labelledby={label ? headingId : undefined}>
      {(label || actions) && (
        <div className="panel-head">
          {label && (
            <Heading className="panel-label" id={headingId}>
              {label}
              {count != null && <span className="panel-count"> · {count}</span>}
            </Heading>
          )}
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      <div
        className={`panel-body${bleed ? " bleed" : ""}${tight ? " tight" : ""} ${bodyClassName}`}
      >
        {children}
      </div>
      {caption && (
        <div className="panel-caption">
          <p>{caption}</p>
        </div>
      )}
    </Tag>
  );
}

function slug(text: string): string {
  return (
    "panel-" +
    text
      .toLowerCase()
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
  );
}
