import { timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { collectionRows, getState, setState } from "@/lib/server/firestore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DEFAULT_SETTINGS = {
  active_strategy: "fsrppo",
  timeframe: "h1",
  bb_period: 20,
  bb_std: 2,
  atr_period: 14,
  sl_atr_mult: 1.5,
  min_band_width_pips: 0,
  rsi_period: 14,
  rsi_overbought: 70,
  rsi_oversold: 30,
  wyckoff_range_period: 20,
  wyckoff_volume_mult: 1.5,
  wyckoff_tp_mult: 2,
  risk_per_trade: 0.005,
  daily_loss_limit: 0.03,
  max_trades_per_day: 4,
  max_spread_pips: 1.5,
  fixed_units: 0,
};

const INSTRUMENTS = [
  { symbol: "EUR/USD", pip: 0.0001, min_lot: 1000, typical_spread_pips: 1.2, quote_currency: "USD" },
  { symbol: "GBP/USD", pip: 0.0001, min_lot: 1000, typical_spread_pips: 1.5, quote_currency: "USD" },
  { symbol: "USD/JPY", pip: 0.01, min_lot: 1000, typical_spread_pips: 1.2, quote_currency: "JPY" },
  { symbol: "XAU/USD", pip: 0.01, min_lot: 1, typical_spread_pips: 35, quote_currency: "USD" },
];

function authorized(request: NextRequest): boolean {
  const expected = process.env.BOT_API_TOKEN || "";
  const provided = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || "";
  if (!expected || expected.length !== provided.length) return false;
  return timingSafeEqual(Buffer.from(expected), Buffer.from(provided));
}

function json(value: unknown, status = 200) {
  return NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function pathOf(context: RouteContext): Promise<string> {
  return (await context.params).path.join("/");
}

async function settings() {
  const overrides = await getState<Record<string, unknown>>("settings_override", {});
  return { ...DEFAULT_SETTINGS, ...overrides };
}

async function snapshot() {
  return getState<Record<string, any>>("runtime_snapshot", {
    updated_at: null,
    status: {
      running: true,
      paused: false,
      halted_today: false,
      connected: false,
      mode: "paper-scheduled",
      active_strategy: "fsrppo",
      account: {},
      stats: {},
      last_candle: null,
      net_position: 0,
    },
    prices: null,
    positions: [],
    candles: {},
  });
}

export async function GET(request: NextRequest, context: RouteContext) {
  if (!authorized(request)) return json({ detail: "token invalido o ausente" }, 401);
  const path = await pathOf(context);
  const current = await snapshot();

  if (path === "snapshot") return json(current);
  if (path === "status") return json(current.status);
  if (path === "positions") return json(current.positions || []);
  if (path === "settings") return json(await settings());
  if (path === "credentials") {
    return json({ configured: true, connection: "Demo", user_masked: "GitHub Secret" });
  }
  if (path === "candles") {
    const timeframe = request.nextUrl.searchParams.get("tf") || "h1";
    return json(current.candles?.[timeframe] || { candles: [], bands: [] });
  }
  if (path === "trades" || path === "equity" || path === "logs") {
    const limit = Math.min(Number(request.nextUrl.searchParams.get("limit") || 200), 2000);
    const rows = await collectionRows(path);
    const key = path === "trades" ? "exit_time" : path === "equity" ? "ts" : "ts";
    rows.sort((a, b) => String(a[key] || "").localeCompare(String(b[key] || "")));
    return json(path === "trades" ? rows.reverse().slice(0, limit) : rows.slice(-limit));
  }
  if (path === "models") return json({ active: null, models: [] });
  if (path === "instruments") return json({ instruments: INSTRUMENTS });
  if (path === "selection/latest") return json(await getState("market_selection", { rows: [] }));
  if (path === "training/datasets") return json({ datasets: [] });
  if (path === "training") return json({ status: "idle", note: "Entrenamiento disponible en GitHub Actions" });
  if (path === "backtest") return json(await getState("last_backtest", { status: "idle" }));
  return json({ ok: false, error: "Endpoint no disponible en el runtime gratuito" }, 404);
}

export async function POST(request: NextRequest, context: RouteContext) {
  if (!authorized(request)) return json({ detail: "token invalido o ausente" }, 401);
  const path = await pathOf(context);
  const body = await request.json().catch(() => ({}));

  if (path === "settings") {
    const previous = await getState<Record<string, unknown>>("settings_override", {});
    await setState("settings_override", { ...previous, ...body });
    return json({ ok: true, settings: await settings() });
  }
  if (path === "control/pause" || path === "control/resume") {
    const running = path.endsWith("resume");
    await setState("running", running);
    const current = await snapshot();
    return json({ ok: true, status: { ...current.status, running, paused: !running } });
  }
  if (path === "close-all" || path.startsWith("close/")) {
    await setState("force_flatten", true);
    return json({ ok: true, closed: 1, queued: true });
  }
  if (path === "credentials") {
    return json({ ok: false, error: "Las credenciales solo se cambian en GitHub Secrets" }, 409);
  }
  return json({ ok: false, error: "Operacion pesada no disponible en Vercel" }, 409);
}

export async function DELETE(request: NextRequest) {
  if (!authorized(request)) return json({ detail: "token invalido o ausente" }, 401);
  return json({ ok: false, error: "Los modelos se administran fuera del runtime gratuito" }, 409);
}
