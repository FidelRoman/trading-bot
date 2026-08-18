"use client";

import { useEffect } from "react";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import MetricRow from "./MetricRow";
import Notice from "./ui/Notice";
import { readAccount } from "@/lib/account";
import { useLive } from "@/lib/live";

export default function Shell({ children }: { children: React.ReactNode }) {
  const { syncError, status } = useLive();
  const account = readAccount(status);

  /* El territorio lo lleva el papel: la cuenta tiñe el fondo de la página
     entera, en todos los anchos. Es la señal que no puede perderse. */
  useEffect(() => {
    document.documentElement.dataset.account = account.kind;
  }, [account.kind]);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        Saltar al contenido
      </a>
      <Sidebar />
      <div className="sheet">
        <Topbar />
        <MetricRow />
        <main className="page" id="main-content" tabIndex={-1}>
          {syncError && (
            <Notice tone="danger" title="Sin sincronizar.">
              {syncError}
            </Notice>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
