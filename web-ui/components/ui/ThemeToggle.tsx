"use client";
/* La lámina impresa o la lámina en la pantalla del instrumento. Por defecto
   manda el sistema; la elección explícita se recuerda. */

import { useEffect, useState } from "react";
import Icon from "./Icon";

type Choice = "light" | "dark" | null;

export default function ThemeToggle() {
  const [choice, setChoice] = useState<Choice>(null);
  // El soporte real solo se conoce en el cliente: calcularlo durante el render
  // rompería la hidratación del export estático.
  const [showingDark, setShowingDark] = useState<boolean | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem("lamina-theme");
    const explicit = stored === "light" || stored === "dark" ? stored : null;
    setChoice(explicit);
    setShowingDark(
      explicit ? explicit === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }, []);

  function apply(next: Choice) {
    setChoice(next);
    if (next) {
      document.documentElement.setAttribute("data-theme", next);
      window.localStorage.setItem("lamina-theme", next);
      setShowingDark(next === "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
      window.localStorage.removeItem("lamina-theme");
      setShowingDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }
  }

  // Hasta saber el soporte, el botón no promete un destino que quizá no sea.
  if (showingDark === null) {
    return (
      <button type="button" className="btn quiet" aria-label="Cambiar de soporte" disabled>
        <Icon name="moon" />
      </button>
    );
  }

  return (
    <button
      type="button"
      className="btn quiet"
      onClick={() => apply(showingDark ? "light" : "dark")}
      onDoubleClick={() => apply(null)}
      title={
        choice
          ? "Cambiar de soporte. Doble clic para volver a seguir al sistema."
          : "Cambiar de soporte (ahora sigue al sistema)"
      }
      aria-label={showingDark ? "Cambiar a lámina impresa" : "Cambiar a lámina en pantalla"}
    >
      <Icon name={showingDark ? "sun" : "moon"} />
    </button>
  );
}
