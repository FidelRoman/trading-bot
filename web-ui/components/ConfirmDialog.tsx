"use client";

import { useEffect, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: React.ReactNode;
  /** Qué pasa de verdad en esta cuenta. Se muestra aparte, en tinta de aviso. */
  consequence?: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  consequence,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cancelRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
      if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
        );
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" onMouseDown={() => !busy && onCancel()}>
      <section
        ref={dialogRef}
        className={`dialog${danger ? " danger" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-body">
          <h2 id="confirm-title">{title}</h2>
          <div id="confirm-description" className="dialog-copy">
            {description}
          </div>
          {consequence && (
            <p
              className="dialog-copy"
              style={{ marginTop: "var(--s-3)", color: danger ? "var(--short)" : "var(--warn)" }}
            >
              {consequence}
            </p>
          )}
        </div>
        <div className="dialog-actions">
          <button ref={cancelRef} className="btn" type="button" disabled={busy} onClick={onCancel}>
            Cancelar
          </button>
          <button
            className={`btn ${danger ? "danger solid" : "primary"}`}
            type="button"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Procesando…" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
