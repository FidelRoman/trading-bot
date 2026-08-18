"use client";
/* Un control consecuente enseña su alcance antes de accionarse: al apuntar o
   enfocar DETENER BOT o CERRAR TODAS se resalta exactamente lo que va a
   afectar. Los estilos viven en globals.css bajo html[data-reaching]. */

import { useEffect, useMemo } from "react";

export type ReachKey = "positions" | "engine";

export function useReach(key: ReachKey) {
  useEffect(() => {
    return () => {
      if (document.documentElement.dataset.reaching === key) {
        delete document.documentElement.dataset.reaching;
      }
    };
  }, [key]);

  return useMemo(
    () => ({
      onMouseEnter: () => {
        document.documentElement.dataset.reaching = key;
      },
      onMouseLeave: () => {
        if (document.documentElement.dataset.reaching === key)
          delete document.documentElement.dataset.reaching;
      },
      onFocus: () => {
        document.documentElement.dataset.reaching = key;
      },
      onBlur: () => {
        if (document.documentElement.dataset.reaching === key)
          delete document.documentElement.dataset.reaching;
      },
    }),
    [key]
  );
}
