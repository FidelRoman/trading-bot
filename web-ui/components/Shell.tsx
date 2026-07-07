"use client";

import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import MetricRow from "./MetricRow";

export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        <MetricRow />
        <div className="page">{children}</div>
      </div>
    </div>
  );
}
