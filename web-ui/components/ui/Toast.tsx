"use client";
/* Confirmaciones efímeras de acción. Antes cada panel inventaba su sitio para
   decir "orden enviada": el mensaje del dashboard aparecía en la cabecera del
   registro, el de ajustes junto al botón, el del picker en ninguna parte. */

import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import Notice, { type Tone } from "./Notice";

interface ToastItem {
  id: number;
  text: React.ReactNode;
  tone: Tone;
}

const ToastContext = createContext<{ push: (text: React.ReactNode, tone?: Tone) => void }>({
  push: () => {},
});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((text: React.ReactNode, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current, { id, text, tone }]);
    setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 6000);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {items.length > 0 && (
        <div className="toast-stack">
          {items.map((item) => (
            <div className="toast" key={item.id}>
              <Notice tone={item.tone}>{item.text}</Notice>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
