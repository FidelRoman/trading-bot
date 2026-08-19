/**
 * Utilidades de formato y tipado específicas para clases de activo:
 * - Divisas (Forex)
 * - Acciones (Shares / Stocks)
 * - CFD (Índices, Materias Primas, Metales, Deuda)
 * - Criptomonedas
 */

import { fmt, fmtPx } from "./format";

export type AssetCategory =
  | "forex"
  | "share"
  | "cfd_index"
  | "cfd_commodity"
  | "cfd_metal"
  | "cfd_treasury"
  | "crypto"
  | "other";

const FOREX_CURRENCIES = new Set([
  "EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "SEK", "NOK",
  "SGD", "HKD", "MXN", "ZAR", "TRY", "PLN", "CZK", "HUF", "ILS", "DKK"
]);

const METALS = new Set(["XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER", "PLATINUM"]);
const CRYPTOS = new Set(["BTC", "ETH", "SOL", "XRP", "LTC", "ADA", "DOT", "DOGE", "AVAX", "BNB"]);
const COMMODITY_HINTS = ["OIL", "NGAS", "GAS", "COPPER", "WHEAT", "SOYB", "CORN", "SUGAR", "COFFEE"];
const INDEX_HINTS = ["US30", "NAS100", "SPX500", "GER30", "GER40", "UK100", "JPN225", "ESP35", "FRA40", "EUSTX50", "HKG33", "CHN50", "AUS200", "VOLX"];

export function getAssetCategory(
  symbol?: string | null,
  assetClass?: string | null
): AssetCategory {
  const sym = (symbol ?? "").trim().toUpperCase();
  const rawClass = (assetClass ?? "").trim().toLowerCase();

  if (rawClass === "bullion" || METALS.has(sym.split("/")[0])) return "cfd_metal";
  if (rawClass === "crypto" || CRYPTOS.has(sym.split("/")[0])) return "crypto";
  if (rawClass === "share") return "share";
  if (rawClass === "index") return "cfd_index";
  if (rawClass === "commodity") return "cfd_commodity";
  if (rawClass === "treasury") return "cfd_treasury";
  if (rawClass === "forex") return "forex";

  if (sym.includes("/")) {
    const [base, quote] = sym.split("/");
    if (METALS.has(base)) return "cfd_metal";
    if (CRYPTOS.has(base) || CRYPTOS.has(quote)) return "crypto";
    if (FOREX_CURRENCIES.has(base) && FOREX_CURRENCIES.has(quote)) return "forex";
    return "other";
  }

  if (COMMODITY_HINTS.some((h) => sym.includes(h))) return "cfd_commodity";
  if (INDEX_HINTS.some((h) => sym.includes(h)) || /\d/.test(sym)) return "cfd_index";
  if (sym.length >= 1 && sym.length <= 5 && /^[A-Z]+$/.test(sym)) return "share";

  return "other";
}

export interface AssetBadgeInfo {
  category: AssetCategory;
  tag: string;
  label: string;
  typeLabel: string;
  tone: "info" | "ok" | "warn" | "accent" | "danger";
  unitName: string;
  unitSingular: string;
  spreadUnit: string;
}

export function getAssetBadgeInfo(
  symbol?: string | null,
  assetClass?: string | null
): AssetBadgeInfo {
  const cat = getAssetCategory(symbol, assetClass);

  switch (cat) {
    case "forex":
      return {
        category: "forex",
        tag: "FX",
        label: "Divisas",
        typeLabel: "Par de Divisas",
        tone: "info",
        unitName: "lotes",
        unitSingular: "lote",
        spreadUnit: "pips",
      };
    case "share":
      return {
        category: "share",
        tag: "ACC",
        label: "Acción",
        typeLabel: "Acción al Contado",
        tone: "accent",
        unitName: "acciones",
        unitSingular: "acción",
        spreadUnit: "$",
      };
    case "cfd_metal":
      return {
        category: "cfd_metal",
        tag: "ORO",
        label: "Metal",
        typeLabel: "CFD Metal Precioso",
        tone: "warn",
        unitName: "contratos",
        unitSingular: "contrato",
        spreadUnit: "pts",
      };
    case "cfd_index":
      return {
        category: "cfd_index",
        tag: "CFD",
        label: "Índice",
        typeLabel: "CFD Índice Bursátil",
        tone: "warn",
        unitName: "contratos",
        unitSingular: "contrato",
        spreadUnit: "pts",
      };
    case "cfd_commodity":
      return {
        category: "cfd_commodity",
        tag: "MAT",
        label: "Materia Prima",
        typeLabel: "CFD Materia Prima",
        tone: "warn",
        unitName: "contratos",
        unitSingular: "contrato",
        spreadUnit: "pts",
      };
    case "cfd_treasury":
      return {
        category: "cfd_treasury",
        tag: "BONO",
        label: "Deuda",
        typeLabel: "CFD Bono / Tipo",
        tone: "info",
        unitName: "contratos",
        unitSingular: "contrato",
        spreadUnit: "pts",
      };
    case "crypto":
      return {
        category: "crypto",
        tag: "CRIPTO",
        label: "Cripto",
        typeLabel: "Criptomoneda 24/7",
        tone: "accent",
        unitName: "monedas",
        unitSingular: "moneda",
        spreadUnit: "$",
      };
    default:
      return {
        category: "other",
        tag: "INST",
        label: "Instrumento",
        typeLabel: "Contrato Financiero",
        tone: "info",
        unitName: "uds",
        unitSingular: "ud",
        spreadUnit: "pts",
      };
  }
}

/** Formatea el precio adaptado a la clase de activo */
export function formatPriceByAsset(
  price: number | null | undefined,
  symbol?: string | null,
  assetClass?: string | null,
  digits?: number
): string {
  if (price == null) return "—";
  const cat = getAssetCategory(symbol, assetClass);
  const num = Number(price);

  if (cat === "share") {
    return `$${num.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (cat === "cfd_index") {
    return `${num.toLocaleString("es", { minimumFractionDigits: digits ?? 1, maximumFractionDigits: digits ?? 2 })} pts`;
  }
  if (cat === "cfd_metal") {
    return `$${num.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (cat === "crypto") {
    return `$${num.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  // Forex / default:
  const d = digits != null ? digits : symbol?.includes("JPY") ? 3 : 5;
  return fmtPx(price, d);
}

/** Formatea el volumen / unidades adaptado a la clase de activo */
export function formatVolumeByAsset(
  units: number | null | undefined,
  lotSize = 100000,
  assetClass?: string | null,
  symbol?: string | null,
  compact = false
): string {
  if (units == null) return "—";
  const cat = getAssetCategory(symbol, assetClass);
  const u = Math.abs(Number(units));

  if (cat === "forex" && lotSize >= 100000) {
    const lots = u / lotSize;
    if (compact) return `${fmt(lots, 2)} lotes`;
    return `${fmt(lots, 2)} lotes (${fmt(u, 0)} uds)`;
  }
  if (cat === "share") {
    return `${fmt(u, 0)} ${u === 1 ? "acción" : "acciones"}`;
  }
  if (cat.startsWith("cfd_")) {
    return `${fmt(u, 0)} ${u === 1 ? "contrato" : "contratos"}`;
  }
  if (cat === "crypto") {
    return `${fmt(u, 2)} monedas`;
  }
  return `${fmt(u, 0)} uds`;
}

/** Formatea la protección o distancia (pips o puntos o $) */
export function formatDistanceByAsset(
  pips: number | null | undefined,
  assetClass?: string | null,
  symbol?: string | null
): string {
  if (pips == null) return "—";
  const cat = getAssetCategory(symbol, assetClass);
  const value = Number(pips);
  if (cat === "share") {
    return `${value >= 0 ? "+" : ""}$${fmt(value, 2)}`;
  }
  if (cat.startsWith("cfd_")) {
    return `${value >= 0 ? "+" : ""}${fmt(value, 1)} pts`;
  }
  return `${value >= 0 ? "+" : ""}${fmt(value, 1)} pips`;
}
