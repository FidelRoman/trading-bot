"use client";
/* Campo: rótulo de eje, control, y una nota que dice qué significa el número.
   Los límites de riesgo se editaban antes sin decir en ninguna parte qué
   implicaba cada cifra. */

import React, { useId } from "react";

export function Field({
  label,
  note,
  htmlFor,
  children,
}: {
  label: React.ReactNode;
  note?: React.ReactNode;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {note && <span className="field-note">{note}</span>}
    </div>
  );
}

export function NumberField({
  label,
  note,
  value,
  onChange,
  min,
  max,
  step,
  disabled,
  suffix,
}: {
  label: React.ReactNode;
  note?: React.ReactNode;
  value: number | "";
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  suffix?: string;
}) {
  const id = useId();
  return (
    <Field label={label} note={note} htmlFor={id}>
      <input
        id={id}
        className="input"
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-describedby={suffix ? `${id}-suffix` : undefined}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {suffix && (
        <span className="sr-only" id={`${id}-suffix`}>
          {suffix}
        </span>
      )}
    </Field>
  );
}

export function SelectField({
  label,
  note,
  value,
  onChange,
  disabled,
  children,
}: {
  label: React.ReactNode;
  note?: React.ReactNode;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <Field label={label} note={note} htmlFor={id}>
      <select
        id={id}
        className="select"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </Field>
  );
}
