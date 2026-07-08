"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLive } from "@/lib/live";

const NAV = [
  { href: "/", ico: "▦", label: "Dashboard" },
  { href: "/strategies", ico: "⚙", label: "Estrategias" },
  { href: "/settings", ico: "🔧", label: "Ajustes" },
  { href: "/history", ico: "⟲", label: "Historial" },
  { href: "/activity", ico: "∿", label: "Monitor de Actividad" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { status } = useLive();
  const connected = status?.connected ?? false;
  const mode = status?.mode ?? "—";

  return (
    <aside className="sidebar">
      <div className="side-brand">
        <div className="avatar">FX</div>
        <div>
          <div className="brand-title">FX-PRO TRADER</div>
          <div className="brand-sub">
            <span className="dot-live" style={{ background: connected ? "#4ade80" : "#f0716a" }} />
            <span>{connected ? "Sesión activa" : "Sin sesión"}</span>
          </div>
        </div>
      </div>

      <nav className="nav">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className={`nav-item${pathname === n.href ? " active" : ""}`}
          >
            <span className="ico">{n.ico}</span> {n.label}
          </Link>
        ))}
      </nav>

      <div className="side-foot">
        <span className={`chip${mode === "simulado" ? " warn" : " ok"}`}>
          {mode.toUpperCase()}
        </span>
        <span className={`chip${connected ? " ok" : " warn"}`}>
          {connected ? "CONECTADO" : "SIN CONEXIÓN"}
        </span>
      </div>
    </aside>
  );
}
