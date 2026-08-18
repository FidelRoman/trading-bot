"use client";
/* Pestañas navegables por teclado. Las de Modelos declaraban role="tab" y
   aria-selected pero no respondían a las flechas, que es justo lo que un lector
   de pantalla anuncia que se puede hacer. */

import { useRef } from "react";

export default function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  function onKeyDown(event: React.KeyboardEvent) {
    const index = tabs.findIndex((t) => t.value === value);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    onChange(tabs[next].value);
    ref.current?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
  }

  return (
    <div className="seg" role="tablist" aria-label={label} ref={ref} onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          id={`tab-${tab.value}`}
          aria-selected={value === tab.value}
          aria-controls={`panel-${tab.value}`}
          tabIndex={value === tab.value ? 0 : -1}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
