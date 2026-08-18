"use client";
/* Un solo juego de iconos, dibujados sobre la misma retícula de 24 con el mismo
   trazo. Sustituye a los símbolos unicode sueltos (⤓ ◈ ⟳ ✓ ✕ ★ ⧉ ⇄ ∿ ◫ ⟲) que
   hacían de iconografía en las cabeceras de tarjeta. */

export type IconName =
  | "operation"
  | "history"
  | "activity"
  | "signal"
  | "train"
  | "models"
  | "strategy"
  | "settings"
  | "close"
  | "check"
  | "alert"
  | "download"
  | "refresh"
  | "play"
  | "pause"
  | "trash"
  | "sun"
  | "moon"
  | "menu"
  | "sortAsc"
  | "sortDesc"
  | "plus"
  | "minus"
  | "star"
  | "compare";

const PATHS: Record<IconName, React.ReactNode> = {
  operation: (
    <>
      <path d="M4 4v16h16" />
      <path d="M7 15l4-6 3 4 4-7" />
    </>
  ),
  history: (
    <>
      <path d="M4 12a8 8 0 1 0 2.4-5.7L4 8" />
      <path d="M4 4v4h4" />
      <path d="M12 8v4.5l3 1.8" />
    </>
  ),
  activity: <path d="M3 15l3.5-6 3 4 3-8 3.5 10 2-3H21" />,
  signal: <path d="M3 12c3-8 6 8 9 0s6 8 9 0" />,
  train: (
    <>
      <path d="M4 19l7-14 7 14" />
      <path d="M7.5 13h9" />
    </>
  ),
  models: (
    <>
      <rect x="3.5" y="3.5" width="11" height="11" rx="1" />
      <path d="M8 20.5h12.5V8" />
    </>
  ),
  strategy: (
    <>
      <circle cx="12" cy="12" r="2.5" />
      <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2" />
    </>
  ),
  settings: (
    <>
      <path d="M4 6.5h8M16.5 6.5H20M4 12h3M11 12h9M4 17.5h6.5M15 17.5H20" />
      <circle cx="14" cy="6.5" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="12.5" cy="17.5" r="2" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M4.5 12.5l5 5 10-11" />,
  alert: (
    <>
      <path d="M12 4.5L21 19.5H3z" />
      <path d="M12 10v4.5M12 17.2v.1" />
    </>
  ),
  download: (
    <>
      <path d="M12 3.5v11" />
      <path d="M7.5 10.5L12 15l4.5-4.5" />
      <path d="M4 19.5h16" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.4-5.7" />
      <path d="M20 4v4.5h-4.5" />
    </>
  ),
  play: <path d="M7 4.5l12 7.5-12 7.5z" />,
  pause: <path d="M8.5 5v14M15.5 5v14" />,
  trash: (
    <>
      <path d="M4.5 6.5h15" />
      <path d="M9.5 6.5V4.5h5v2" />
      <path d="M6.5 6.5l1 13h9l1-13" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.2 5.2l1.8 1.8M17 17l1.8 1.8M18.8 5.2L17 7M7 17l-1.8 1.8" />
    </>
  ),
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  sortAsc: <path d="M12 18.5V6M7 11l5-5 5 5" />,
  sortDesc: <path d="M12 5.5V18M7 13l5 5 5-5" />,
  plus: <path d="M12 5.5v13M5.5 12h13" />,
  minus: <path d="M5.5 12h13" />,
  star: <path d="M12 4l2.5 5.2 5.5.8-4 4 1 5.6-5-2.7-5 2.7 1-5.6-4-4 5.5-.8z" />,
  compare: (
    <>
      <path d="M4 8.5h13M13.5 5l3.5 3.5-3.5 3.5" />
      <path d="M20 15.5H7M10.5 12L7 15.5l3.5 3.5" />
    </>
  ),
};

export default function Icon({
  name,
  size = 16,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
