/** El cero negativo existe en coma flotante y se cuela en la interfaz: un P&L de
 *  −0,0001 se redondea a "-0,00" y, como `-0 >= 0` es cierto en JavaScript, el
 *  signo positivo se le añadía delante y salía "+-0,00". Se normaliza aquí, una
 *  vez, en lugar de en cada sitio que formatea una cifra. */
const zero = (n: number, d: number): number => (Math.abs(n) < 0.5 * 10 ** -d ? 0 : n);

export const fmt = (n: number | null | undefined, d = 2): string =>
  n == null
    ? "—"
    : Number(zero(Number(n), d)).toLocaleString("es", {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      });

/** Precio con los decimales del instrumento: US30 no se muestra con 5. */
export const fmtPx = (n: number | null | undefined, digits = 5): string =>
  n == null ? "—" : Number(n).toFixed(Math.min(Math.max(digits, 0), 8));

export const money = (n: number | null | undefined): string => (n == null ? "—" : "$" + fmt(n));

export const sign = (n: number | null | undefined, suf = "", d = 2): string => {
  if (n == null) return "—";
  const value = zero(Number(n), d);
  return (value > 0 ? "+" : "") + fmt(value, d) + suf;
};

/** Importe con signo delante del símbolo: "−$1,74", "+$3,20", "$0,00". */
export const signedMoney = (n: number | null | undefined): string => {
  if (n == null) return "—";
  const value = zero(Number(n), 2);
  const mark = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${mark}$${fmt(Math.abs(value))}`;
};

export const isoShort = (iso: string | null | undefined): string =>
  iso ? iso.slice(0, 16).replace("T", " ") : "—";

/** Información direccional con signo explícito: "+ COMPRA ▲" / "− VENTA ▼" */
export interface DirectionSign {
  side: "long" | "short";
  text: string;
  sign: "+" | "−";
  arrow: "▲" | "▼";
  fullLabel: string;
  tone: "pos" | "neg";
  markClass: string;
}

export const getDirectionSign = (side?: "long" | "short" | string | null): DirectionSign => {
  const isLong = side === "long" || side === "buy";
  return {
    side: isLong ? "long" : "short",
    text: isLong ? "Compra" : "Venta",
    sign: isLong ? "+" : "−",
    arrow: isLong ? "▲" : "▼",
    fullLabel: isLong ? "+ COMPRA ▲" : "− VENTA ▼",
    tone: isLong ? "pos" : "neg",
    markClass: isLong ? "ok" : "danger",
  };
};

/** Unidades con signo de dirección: "+10.000" / "−10.000" */
export const signedUnits = (
  units: number | null | undefined,
  side?: "long" | "short" | string | null,
  d = 0
): string => {
  if (units == null) return "—";
  const isLong = side === "long" || side === "buy";
  const mark = isLong ? "+" : "−";
  return `${mark}${fmt(Math.abs(units), d)}`;
};

/** Pips con signo explícito: "+14.2" / "−8.5" */
export const signedPips = (pips: number | null | undefined, suffix = " pips", d = 1): string => {
  if (pips == null) return "—";
  const val = zero(Number(pips), d);
  const mark = val > 0 ? "+" : val < 0 ? "−" : "";
  return `${mark}${fmt(Math.abs(val), d)}${suffix}`;
};
