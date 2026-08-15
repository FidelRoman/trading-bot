"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLive } from "@/lib/live";

const NAV_GROUPS = [
  {
    label: "OPERACIÓN",
    items: [
      { href: "/", icon: "operation", label: "Operación" },
      { href: "/history", icon: "history", label: "Historial" },
      { href: "/activity", icon: "activity", label: "Actividad" },
    ],
  },
  {
    label: "INVESTIGACIÓN",
    items: [
      { href: "/fsr", icon: "signal", label: "Señal FSR" },
      { href: "/train", icon: "train", label: "Entrenamiento" },
      { href: "/models", icon: "models", label: "Modelos" },
      { href: "/strategies", icon: "strategy", label: "Estrategias" },
    ],
  },
  {
    label: "SISTEMA",
    items: [{ href: "/settings", icon: "settings", label: "Ajustes" }],
  },
];

function NavIcon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    operation: <><path d="M4 13h4l2-7 4 12 2-5h4" /><path d="M4 4v16h16" /></>,
    history: <><path d="M4 12a8 8 0 1 0 2.3-5.7L4 8" /><path d="M4 4v4h4M12 8v5l3 2" /></>,
    activity: <><path d="M5 19V9M10 19V5M15 19v-7M20 19V3" /></>,
    signal: <><path d="M3 12c3-8 6 8 9 0s6 8 9 0" /></>,
    train: <><path d="M5 18 12 4l7 14M8 14h8" /></>,
    models: <><rect x="4" y="4" width="12" height="12" rx="2" /><path d="M8 20h12V8" /></>,
    strategy: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /></>,
    settings: <><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4" /><circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="14" cy="18" r="2" /></>,
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">{paths[name]}</svg>;
}

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { status } = useLive();
  const connected = status?.connected ?? false;
  const connection = status?.account?.connection ?? "";
  const real = Boolean(status?.live_execution && (connection === "Real" || status?.mode.includes("real")));
  const demo = Boolean(status?.live_execution && !real);
  const modeLabel = real ? "CUENTA REAL" : demo ? "CUENTA DEMO" : "SIMULADO";

  useEffect(() => setOpen(false), [pathname]);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="side-brand">
          <div className="avatar">FX</div>
          <div>
            <div className="brand-title">FX-PRO TRADER</div>
            <div className="brand-sub">
              <span className={`connection-dot${connected ? " connected" : ""}`} />
              <span>{connected ? "Sesión activa" : "Sin sesión"}</span>
            </div>
          </div>
        </div>
        <button
          className="mobile-nav-toggle"
          type="button"
          aria-expanded={open}
          aria-controls="primary-navigation"
          aria-label={open ? "Cerrar navegación" : "Abrir navegación"}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true">{open ? "×" : "≡"}</span>
        </button>
      </div>

      <nav id="primary-navigation" className={`nav${open ? " open" : ""}`} aria-label="Navegación principal">
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item${pathname === item.href ? " active" : ""}`}
                aria-current={pathname === item.href ? "page" : undefined}
              >
                <NavIcon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            ))}
          </div>
        ))}
      </nav>

      <div className="side-foot">
        <span className={`chip ${real ? "real" : demo ? "ok" : "warn"}`}>
          {modeLabel}
        </span>
        <span className={`chip${connected ? " ok" : " warn"}`}>
          {connected ? "CONECTADO" : "SIN CONEXIÓN"}
        </span>
      </div>
    </aside>
  );
}
