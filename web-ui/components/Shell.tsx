"use client";

import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import MetricRow from "./MetricRow";

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hideKpis = ["/strategies", "/settings", "/activity"].includes(pathname);

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        {!hideKpis && <MetricRow />}
        <div className="page">{children}</div>
      </div>
    </div>
  );
}
