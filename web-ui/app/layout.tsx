import type { Metadata } from "next";
import { LiveProvider } from "@/lib/live";
import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "FX COMMAND CENTER — EUR/USD M15",
  description: "Bot de trading EUR/USD con Bandas de Bollinger sobre FXCM",
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230e1013'/%3E%3Cpath d='M16 5 27 16 16 27 5 16Z' fill='none' stroke='%239aa8f8' stroke-width='2.5'/%3E%3C/svg%3E",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;600;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <LiveProvider>
          <Shell>{children}</Shell>
        </LiveProvider>
      </body>
    </html>
  );
}
