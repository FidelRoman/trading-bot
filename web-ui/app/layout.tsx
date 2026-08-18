import type { Metadata } from "next";
import localFont from "next/font/local";
import Script from "next/script";
import { LiveProvider } from "@/lib/live";
import { ToastProvider } from "@/components/ui/Toast";
import Shell from "@/components/Shell";
import "./globals.css";

/* Las fuentes viajan en el repositorio: la app arranca y se compila sin red. */
const sans = localFont({
  src: "./fonts/LibreFranklin-Variable.woff2",
  weight: "400 800",
  display: "swap",
  variable: "--font-sans",
  fallback: ["system-ui", "sans-serif"],
});

const mono = localFont({
  src: "./fonts/JetBrainsMono-Variable.woff2",
  weight: "400 700",
  display: "swap",
  variable: "--font-mono",
  fallback: ["ui-monospace", "monospace"],
});

export const metadata: Metadata = {
  title: "FSRPPO·BOT",
  description:
    "Consola de operación del bot FSRPPO sobre FXCM: divisas, materias primas, índices, acciones y CFD",
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23efece4'/%3E%3Cpath d='M5 27V5M5 27h22' stroke='%2314171a' stroke-width='2'/%3E%3Cpath d='M9 21l5-9 4 5 5-11' stroke='%230a6b4a' stroke-width='2.5' fill='none'/%3E%3C/svg%3E",
  },
};

const DIRECTION_CONTRACT = `<!--
THESIS: this console is the live plate of the paper it implements; it refuses the dark
card dashboard with neon candles and glassy panels.
OWN-WORLD: paper or instrument ground, 1px hairlines, zero radii, labelled panels closed
by figure captions, two signal inks (green long, red short) plus annotation blue, Libre
Franklin with tabular figures, mono reserved for logs and run ids. Account territory
tints the whole page ground.
STORY: the operator sees what the machine is doing, in which account, and can stop it
within one reach, at any width.
FIRST VIEWPORT: full-width status band carrying territory, engine state and the
start/stop controls; below it the plate - instrument figure at large scale on the left,
readouts column on the right, tables under the figure.
FORM: candidate 3 of 7 on the grounded list; seed key 880fe5e2, code-led.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish
review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
-->`;

/* Se ejecuta antes de pintar: sin esto el tema elegido parpadea en cada carga. */
const THEME_BOOT = `(function(){try{var t=localStorage.getItem("lamina-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <Script id="lamina-theme-boot" strategy="beforeInteractive">
          {THEME_BOOT}
        </Script>
      </head>
      <body>
        {/* El contrato de dirección va como comentario HTML real: un comentario JSX es
            de JavaScript y el build lo borra, así que nadie podría auditarlo. */}
        <div hidden dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        <LiveProvider>
          <ToastProvider>
            <Shell>{children}</Shell>
          </ToastProvider>
        </LiveProvider>
      </body>
    </html>
  );
}
