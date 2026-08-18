"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon, { type IconName } from "./ui/Icon";
import Mark from "./ui/Mark";
import { readAccount } from "@/lib/account";
import { useLive } from "@/lib/live";

const NAV_GROUPS: { label: string; items: { href: string; icon: IconName; label: string }[] }[] = [
  {
    label: "Operación",
    items: [
      { href: "/", icon: "operation", label: "Operación" },
      { href: "/history", icon: "history", label: "Historial" },
      { href: "/activity", icon: "activity", label: "Actividad" },
    ],
  },
  {
    label: "Investigación",
    items: [
      { href: "/fsr", icon: "signal", label: "Señal FSR" },
      { href: "/train", icon: "train", label: "Entrenamiento" },
      { href: "/models", icon: "models", label: "Modelos" },
      { href: "/strategies", icon: "strategy", label: "Estrategias" },
    ],
  },
  {
    label: "Sistema",
    items: [{ href: "/settings", icon: "settings", label: "Ajustes" }],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { status } = useLive();
  const connected = status?.connected ?? false;
  const account = readAccount(status);

  useEffect(() => setOpen(false), [pathname]);

  return (
    <aside className="rail">
      <div className="rail-head">
        <div className="rail-mark">
          <span className="rail-name">FSRPPO·BOT</span>
          <span className="rail-sub">Consola de operación</span>
        </div>
        <button
          className="rail-toggle"
          type="button"
          aria-expanded={open}
          aria-controls="primary-navigation"
          aria-label={open ? "Cerrar navegación" : "Abrir navegación"}
          onClick={() => setOpen((value) => !value)}
        >
          <Icon name={open ? "close" : "menu"} size={18} />
        </button>
      </div>

      <nav
        id="primary-navigation"
        className={`nav${open ? " open" : ""}`}
        aria-label="Navegación principal"
      >
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="nav-item"
                aria-current={pathname === item.href ? "page" : undefined}
              >
                <Icon name={item.icon} className="nav-icon" />
                <span>{item.label}</span>
              </Link>
            ))}
          </div>
        ))}
      </nav>

      {/* Modo y conexión nunca se ocultan, tampoco en móvil. */}
      <div className="rail-foot">
        <Mark tone={account.tone === "danger" ? "danger" : account.tone === "info" ? "info" : "warn"}>
          {account.label}
        </Mark>
        <Mark tone={connected ? "ok" : "warn"} dot live={connected}>
          {connected ? "Conectado" : "Sin conexión"}
        </Mark>
      </div>
    </aside>
  );
}
