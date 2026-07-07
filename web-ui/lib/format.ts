export const fmt = (n: number | null | undefined, d = 2): string =>
  n == null
    ? "—"
    : Number(n).toLocaleString("es", { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmtPx = (n: number | null | undefined): string =>
  n == null ? "—" : Number(n).toFixed(5);

export const money = (n: number | null | undefined): string => (n == null ? "—" : "$" + fmt(n));

export const sign = (n: number | null | undefined, suf = ""): string =>
  n == null ? "—" : (n >= 0 ? "+" : "") + fmt(n) + suf;

export const isoShort = (iso: string | null | undefined): string =>
  iso ? iso.slice(0, 16).replace("T", " ") : "—";
