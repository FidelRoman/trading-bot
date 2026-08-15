"use client";

import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import MetricRow from "./MetricRow";
import { useLive } from "@/lib/live";

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { syncError } = useLive();
  const hideKpis = ["/strategies", "/settings", "/activity"].includes(pathname);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <Sidebar />
      <div className="main">
        <Topbar />
        {syncError && <div className="global-alert" role="alert">{syncError}</div>}
        {!hideKpis && <MetricRow />}
        <main className="page" id="main-content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
