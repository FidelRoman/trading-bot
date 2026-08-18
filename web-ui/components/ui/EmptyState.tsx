"use client";
/* Un estado vacío enseña la interfaz; "Sin datos" no enseña nada. */

import type React from "react";

export default function EmptyState({
  title,
  hint,
  action,
}: {
  title: React.ReactNode;
  hint?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-title">{title}</span>
      {hint && <span className="empty-hint">{hint}</span>}
      {action && <span style={{ marginTop: "var(--s-2)" }}>{action}</span>}
    </div>
  );
}
