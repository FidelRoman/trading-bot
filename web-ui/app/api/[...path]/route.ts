import { randomUUID, timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { collectionRows, getState, setCollectionDocument, setState } from "@/lib/server/firestore";

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
      running: false,
      paused: true,
      halted_today: false,
      connected: false,
      mode: "fxcm-demo",
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

type Connection = "Demo" | "Real";
type AccountSelection = { connection: Connection; real_confirmed_at?: string | null };

async function accountSelection(): Promise<AccountSelection> {
  const saved = await getState<Partial<AccountSelection>>("fxcm_connection", {});
  return saved.connection === "Real"
    ? { connection: "Real", real_confirmed_at: saved.real_confirmed_at || null }
    : { connection: "Demo", real_confirmed_at: null };
}

async function queuedCommands() {
  const rows = await collectionRows("commands");
  return rows.filter((row) => row.status === "queued");
}

async function enqueueCommand(kind: string, connection: Connection, payload: Record<string, unknown>) {
  const id = randomUUID();
  const command = {
    id,
    kind,
    connection,
    payload,
    status: "queued",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    result: null,
    error: null,
  };
  await setCollectionDocument("commands", id, command);
  return command;
}

async function cancelQueuedOpenCommands() {
  const queued = await queuedCommands();
  await Promise.all(queued
    .filter((command) => command.kind === "open")
    .map((command) => setCollectionDocument("commands", String(command.id), {
      ...command,
      status: "cancelled",
      finished_at: new Date().toISOString(),
      error: "Bot detenido antes de ejecutar la orden",
    })));
  return queued.filter((command) => command.kind === "open").length;
}

function validConnection(value: unknown): value is Connection {
  return value === "Demo" || value === "Real";
}

function numberInRange(value: unknown, min: number, max: number): number | null {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= min && number <= max ? number : null;
}

export async function GET(request: NextRequest, context: RouteContext) {
  if (!authorized(request)) return json({ detail: "token invalido o ausente" }, 401);
  const path = await pathOf(context);
  const current = await snapshot();

  if (path === "snapshot") return json(current);
  if (path === "status") return json(current.status);
  if (path === "positions") return json(current.positions || []);
  if (path === "settings") return json(await settings());
  if (path === "credentials" || path === "account") {
    const account = await accountSelection();
    return json({
      ...account,
      configured: { demo: true, real: true },
      running: await getState("running", false),
      queued_commands: (await queuedCommands()).length,
    });
  }
  if (path === "commands") {
    const commands = await collectionRows("commands");
    return json(commands.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 100));
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
  if (path === "credentials" || path === "account") {
    const connection = body.connection;
    if (!validConnection(connection)) return json({ ok: false, error: "Selecciona Demo o Real" }, 400);
    if (await getState("running", false)) {
      return json({ ok: false, error: "Detén el bot antes de cambiar de cuenta" }, 409);
    }
    if ((await queuedCommands()).some((command) => command.kind === "open")) {
      return json({ ok: false, error: "Hay aperturas pendientes; espera o detén el bot para cancelarlas" }, 409);
    }
    if (connection === "Real" && body.confirm_real !== true) {
      return json({ ok: false, error: "Confirma explícitamente el cambio a cuenta Real" }, 409);
    }
    const selection: AccountSelection = {
      connection,
      real_confirmed_at: connection === "Real" ? new Date().toISOString() : null,
    };
    await setState("fxcm_connection", selection);
    return json({ ok: true, ...selection });
  }
  if (path === "control/pause" || path === "control/resume") {
    const running = path.endsWith("resume");
    await setState("running", running);
    const cancelled = running ? 0 : await cancelQueuedOpenCommands();
    const current = await snapshot();
    return json({ ok: true, cancelled, status: { ...current.status, running, paused: !running } });
  }
  if (path === "manual/long" || path === "manual/short") {
    if (!(await getState("running", false))) {
      return json({ ok: false, error: "El bot está detenido. Inícialo antes de enviar una orden." }, 409);
    }
    const lots = numberInRange(body.lots, 0.01, 5);
    const slPips = numberInRange(body.sl_pips, 1, 200);
    const tpPips = numberInRange(body.tp_pips, 1, 200);
    if (lots === null || slPips === null || tpPips === null) {
      return json({ ok: false, error: "Lote, stop y take profit están fuera del rango permitido" }, 400);
    }
    const account = await accountSelection();
    if (account.connection === "Real" && body.confirm_real !== true) {
      return json({ ok: false, error: "Confirma la orden de cuenta Real" }, 409);
    }
    const command = await enqueueCommand("open", account.connection, {
      side: path.endsWith("long") ? "long" : "short",
      lots,
      sl_pips: slPips,
      tp_pips: tpPips,
      confirm_real: account.connection === "Real",
    });
    return json({ ok: true, queued: true, command_id: command.id, connection: account.connection }, 202);
  }
  if (path === "close-all" || path.startsWith("close/")) {
    const account = await accountSelection();
    const kind = path === "close-all" ? "close_all" : "close";
    const command = await enqueueCommand(kind, account.connection, kind === "close"
      ? { trade_id: path.slice("close/".length) }
      : {});
    return json({ ok: true, queued: true, command_id: command.id, connection: account.connection }, 202);
  }
  if (path === "backtest") {
    const source = body.source === "synthetic" ? "synthetic" : body.source === "fxcm" ? "fxcm" : null;
    const timeframe = typeof body.timeframe === "string" ? body.timeframe : "h1";
    const dateFrom = typeof body.date_from === "string" ? body.date_from : "";
    const dateTo = typeof body.date_to === "string" ? body.date_to : "";
    const from = Date.parse(`${dateFrom}T00:00:00Z`);
    const to = Date.parse(`${dateTo}T00:00:00Z`);
    if (!source || !Number.isFinite(from) || !Number.isFinite(to) || to <= from || to - from > 730 * 86_400_000) {
      return json({ ok: false, error: "Usa FXCM o sintético y un rango máximo de 730 días" }, 400);
    }
    const account = await accountSelection();
    const command = await enqueueCommand("backtest", account.connection, {
      source,
      timeframe,
      date_from: dateFrom,
      date_to: dateTo,
      equity: numberInRange(body.equity, 100, 10_000_000) ?? 10_000,
      spread_pips: numberInRange(body.spread_pips, 0, 100) ?? 1.2,
      strategy: typeof body.strategy === "string" ? body.strategy : "bollinger",
      strategy_params: typeof body.strategy_params === "object" && body.strategy_params ? body.strategy_params : {},
      risk_per_trade: numberInRange(body.risk_per_trade, 0.001, 0.02) ?? undefined,
      fixed_units: numberInRange(body.fixed_units, 0, 500_000) ?? 0,
    });
    await setState("last_backtest", { status: "queued", note: "Backtest en cola para GitHub Actions", command_id: command.id });
    return json({ ok: true, queued: true, command_id: command.id }, 202);
  }
  return json({ ok: false, error: "Operacion pesada no disponible en Vercel" }, 409);
}

export async function DELETE(request: NextRequest) {
  if (!authorized(request)) return json({ detail: "token invalido o ausente" }, 401);
  return json({ ok: false, error: "Los modelos se administran fuera del runtime gratuito" }, 409);
}
