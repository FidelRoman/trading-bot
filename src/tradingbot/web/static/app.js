/* FX COMMAND CENTER — gestión completa del bot desde la interfaz. */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString("es", { minimumFractionDigits: d, maximumFractionDigits: d }));
const fmtPx = (n) => (n == null ? "—" : Number(n).toFixed(5));
const money = (n) => (n == null ? "—" : "$" + fmt(n));
const sign = (n, suf = "") => (n == null ? "—" : (n >= 0 ? "+" : "") + fmt(n) + suf);

const state = { view: "dashboard", tf: "m15", lastBid: null, lastAsk: null, equityChart: null };

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " → " + r.status);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

/* ================= charts ================= */
const chartOpts = {
  layout: { background: { color: "transparent" }, textColor: "#8a90a0", fontFamily: "JetBrains Mono" },
  grid: { vertLines: { color: "rgba(138,144,160,0.07)" }, horzLines: { color: "rgba(138,144,160,0.07)" } },
  rightPriceScale: { borderColor: "rgba(138,144,160,0.18)" },
  timeScale: { borderColor: "rgba(138,144,160,0.18)", timeVisible: true, secondsVisible: false },
  crosshair: {
    vertLine: { color: "rgba(154,168,248,0.4)", labelBackgroundColor: "#16181e" },
    horzLine: { color: "rgba(154,168,248,0.4)", labelBackgroundColor: "#16181e" },
  },
  autoSize: true,
};

const candleChart = LightweightCharts.createChart($("chart-candles"), chartOpts);
const candleSeries = candleChart.addCandlestickSeries({
  upColor: "#4ade80", downColor: "#f0716a",
  wickUpColor: "#4ade80", wickDownColor: "#f0716a",
  borderVisible: false,
  priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
});
const mkLine = (color, style) =>
  candleChart.addLineSeries({ color, lineWidth: 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
const upperSeries = mkLine("rgba(154,168,248,0.65)", 2);
const lowerSeries = mkLine("rgba(154,168,248,0.65)", 2);
const midSeries = mkLine("rgba(240,113,106,0.75)", 0);

function ensureEquityChart() {
  if (state.equityChart) return;
  state.equityChart = LightweightCharts.createChart($("chart-equity"), chartOpts);
  state.equitySeries = state.equityChart.addAreaSeries({
    lineColor: "#9aa8f8", lineWidth: 2,
    topColor: "rgba(154,168,248,0.25)", bottomColor: "rgba(154,168,248,0.02)",
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  });
  refreshEquity();
}

/* ================= refresh ================= */
async function refreshCandles() {
  const { candles, bands } = await getJSON(`/api/candles?count=200&tf=${state.tf}`);
  if (!candles.length) return;
  candleSeries.setData(candles);
  upperSeries.setData(bands.map((b) => ({ time: b.time, value: b.upper })));
  midSeries.setData(bands.map((b) => ({ time: b.time, value: b.mid })));
  lowerSeries.setData(bands.map((b) => ({ time: b.time, value: b.lower })));
}

async function refreshEquity() {
  if (!state.equitySeries) return;
  const rows = await getJSON("/api/equity");
  const seen = new Set();
  const data = [];
  for (const r of rows) {
    const t = Math.floor(new Date(r.ts).getTime() / 1000);
    if (!seen.has(t)) { seen.add(t); data.push({ time: t, value: r.equity }); }
  }
  if (data.length) state.equitySeries.setData(data);
}

async function refreshTrades() {
  const trades = await getJSON("/api/trades?limit=200");
  const tbody = document.querySelector("#trades-table tbody");
  $("trades-empty").style.display = trades.length ? "none" : "block";
  tbody.innerHTML = trades.map((t) => {
    const pnlCls = (t.pnl ?? 0) >= 0 ? "pos" : "neg";
    return `<tr>
      <td class="${t.side === "long" ? "dir-long" : "dir-short"}">${t.side === "long" ? "▲ BUY" : "▼ SELL"}</td>
      <td>${fmt(t.units, 0)}</td>
      <td>${fmtPx(t.entry_rate)}</td>
      <td>${fmtPx(t.exit_rate)}</td>
      <td class="${pnlCls}">${t.pips == null ? "—" : fmt(t.pips, 1)}</td>
      <td class="${pnlCls}">${t.pnl == null ? "—" : sign(t.pnl)}</td>
      <td>${(t.reason || "—").toUpperCase()}</td>
      <td>${(t.exit_time || t.entry_time || "").slice(0, 16).replace("T", " ")}</td>
    </tr>`;
  }).join("");

  const markers = trades
    .filter((t) => t.entry_time)
    .map((t) => ({
      time: Math.floor(new Date(t.entry_time).getTime() / 1000 / 900) * 900,
      position: t.side === "long" ? "belowBar" : "aboveBar",
      color: t.side === "long" ? "#4ade80" : "#f0716a",
      shape: t.side === "long" ? "arrowUp" : "arrowDown",
      text: t.side === "long" ? "B" : "S",
    }))
    .sort((a, b) => a.time - b.time);
  if (state.tf === "m15") candleSeries.setMarkers(markers);
  else candleSeries.setMarkers([]);
}

async function refreshLogs() {
  const logs = await getJSON("/api/logs?limit=120");
  const html = logs.map((l) =>
    `<div><span class="log-ts">[${l.ts.slice(11, 19)}]</span><span class="log-${l.level}">${l.message}</span></div>`
  ).join("");
  const mini = $("log-feed"), full = $("log-feed-full");
  mini.innerHTML = html; mini.scrollTop = mini.scrollHeight;
  full.innerHTML = html; full.scrollTop = full.scrollHeight;
}

async function refreshSettings() {
  const s = await getJSON("/api/settings");
  $("s-bb_period").value = s.bb_period;
  $("s-bb_std").value = s.bb_std;
  $("s-atr_period").value = s.atr_period;
  $("s-sl_atr_mult").value = s.sl_atr_mult;
  $("s-risk_per_trade").value = +(s.risk_per_trade * 100).toFixed(2);
  $("s-daily_loss_limit").value = +(s.daily_loss_limit * 100).toFixed(1);
  $("s-max_trades_per_day").value = s.max_trades_per_day;
  $("s-max_spread_pips").value = s.max_spread_pips;
  $("s-fixed_units").value = s.fixed_units;
  $("ctl-bb").textContent = `${s.bb_period},${s.bb_std}`;
}

/* ================= render ================= */
function renderTick(msg) {
  const { bid, ask, spread_pips } = msg.prices;
  const hdr = $("hdr-price");
  hdr.textContent = fmtPx(bid);
  hdr.classList.toggle("down", state.lastBid != null && bid < state.lastBid);
  $("bid").textContent = fmtPx(bid);
  $("ask").textContent = fmtPx(ask);
  $("spread").textContent = fmt(spread_pips, 1);
  const f = $("floating");
  f.textContent = sign(msg.floating_pl);
  f.className = msg.floating_pl >= 0 ? "pos" : "neg";
  state.lastBid = bid; state.lastAsk = ask;
  if (msg.positions) renderPositions(msg.positions);
}

function renderPositions(positions) {
  $("pos-count").textContent = positions.length;
  $("pos-empty").style.display = positions.length ? "none" : "block";
  $("positions-list").innerHTML = positions.map((p) => {
    const pl = p.gross_pl ?? 0;
    const cls = pl >= 0 ? "pos" : "neg";
    const barColor = pl >= 0 ? "#4ade80" : "#f0716a";
    const barW = Math.min(Math.abs(pl) / 100 * 100, 100);
    return `<div class="pos-card">
      <div class="pos-top">
        <span class="badge ${p.side === "long" ? "badge-buy" : "badge-sell"}">${p.side === "long" ? "BUY" : "SELL"}</span>
        <span class="pos-pair">EUR/USD</span>
        <span class="pos-pl ${cls}">${sign(pl)}</span>
        <button class="pos-close" data-close="${p.trade_id}" title="Cerrar posición">✕</button>
      </div>
      <div class="pos-mid">
        <span>Vol: <b>${fmt(p.units / 100000, 2)}</b></span>
        <span>Open: <b>${fmtPx(p.open_rate)}</b></span>
        <span>Cur: <b>${fmtPx(state.lastBid)}</b></span>
      </div>
      <div class="pos-bar"><div class="fill" style="width:${barW}%;background:${barColor}"></div></div>
    </div>`;
  }).join("");
}

function renderStatus(s) {
  const pill = $("status-pill");
  const isOn = !s.paused && !s.halted_today;
  pill.classList.toggle("paused", !isOn);
  $("status-text").textContent = s.halted_today ? "LÍMITE DIARIO" : s.paused ? "PAUSADO" : "OPERANDO";
  $("btn-start").disabled = isOn;
  $("btn-stop").disabled = !isOn;
  $("auto-toggle").checked = !s.paused;
  $("session-text").textContent = s.connected ? "Sesión activa" : "Sin sesión";
  $("session-dot").style.background = s.connected ? "#4ade80" : "#f0716a";

  const mode = $("mode-chip");
  mode.textContent = (s.mode || "—").toUpperCase();
  mode.className = "chip" + (s.mode === "simulado" ? " warn" : " ok");
  const conn = $("conn-chip");
  conn.textContent = s.connected ? "CONECTADO" : "SIN CONEXIÓN";
  conn.className = "chip" + (s.connected ? " ok" : " warn");

  const eq = s.account?.equity;
  $("m-equity").textContent = money(eq);
  const eqSub = $("m-equity-sub");
  eqSub.textContent = sign(s.daily_pl_pct, "% hoy");
  eqSub.className = "m-sub " + (s.daily_pl_pct >= 0 ? "pos" : "neg");

  const usable = s.account?.usable_margin;
  $("m-margin").textContent = money(usable);
  $("m-margin-sub").textContent = eq ? fmt(usable / eq * 100, 1) + "% del equity" : "—";

  const dp = $("m-daypnl");
  dp.textContent = s.daily_pl_abs == null ? "—" : (s.daily_pl_abs >= 0 ? "+" : "") + money(Math.abs(s.daily_pl_abs)).replace("$", s.daily_pl_abs < 0 ? "-$" : "$");
  dp.className = "m-val " + (s.daily_pl_abs >= 0 ? "pos" : "neg");
  $("m-daypnl-sub").textContent = `Trades hoy: ${s.trades_today} / ${s.max_trades_per_day}`;

  const dd = $("m-dd");
  dd.textContent = fmt(s.max_drawdown_pct, 1) + "%";
  dd.className = "m-val " + (s.max_drawdown_pct <= -5 ? "neg" : s.max_drawdown_pct < 0 ? "" : "pos");

  $("h-trades").textContent = s.stats?.trades ?? "—";
  $("h-winrate").textContent = fmt(s.stats?.win_rate_pct, 1) + "%";
  $("h-pf").textContent = s.stats?.profit_factor == null ? "—" : fmt(s.stats.profit_factor);
  $("h-pips").textContent = fmt(s.stats?.total_pips, 1);
}

/* ================= websocket ================= */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  const ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "tick") renderTick(msg);
    else if (msg.type === "status") renderStatus(msg.status);
    else if (msg.type === "candle") { refreshCandles(); refreshTrades(); refreshEquity(); refreshLogs(); }
  };
  ws.onopen = () => { $("live-tag").innerHTML = '<span class="dot-live"></span>LIVE'; };
  ws.onclose = () => {
    clearInterval(ping);
    $("live-tag").textContent = "RECONECTANDO…";
    setTimeout(connectWS, 2000);
  };
}

/* ================= navegación ================= */
function switchView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
  if (name === "activity") { ensureEquityChart(); refreshLogs(); }
  if (name === "history") refreshTrades();
  if (name === "settings") refreshSettings();
}
document.querySelectorAll(".nav-item").forEach((n) => n.addEventListener("click", () => switchView(n.dataset.view)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.goto)));

/* ================= timeframe ================= */
document.querySelectorAll(".tf-btn").forEach((b) =>
  b.addEventListener("click", () => {
    state.tf = b.dataset.tf;
    document.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("active", x === b));
    refreshCandles().then(refreshTrades);
  })
);

/* ================= steppers ================= */
function initStepper(boxId, step, min, max, decimals) {
  const box = $(boxId);
  const input = box.querySelector("input");
  const clamp = (v) => Math.min(Math.max(v, min), max);
  const set = (v) => { input.value = clamp(v).toFixed(decimals); };
  box.querySelector(".st-dec").addEventListener("click", () => set(parseFloat(input.value || 0) - step));
  box.querySelector(".st-inc").addEventListener("click", () => set(parseFloat(input.value || 0) + step));
  input.addEventListener("change", () => set(parseFloat(input.value) || min));
}
initStepper("st-lots", 0.01, 0.01, 5, 2);
initStepper("st-tp", 0.5, 1, 200, 1);
initStepper("st-sl", 0.5, 1, 200, 1);

/* ================= acciones ================= */
async function setRunning(run) {
  const data = await postJSON(`/api/control/${run ? "resume" : "pause"}`);
  if (data.ok) renderStatus(data.status);
  refreshLogs();
}
$("btn-start").addEventListener("click", () => setRunning(true));
$("btn-stop").addEventListener("click", () => setRunning(false));
$("auto-toggle").addEventListener("change", (e) => setRunning(e.target.checked));

function showManualMsg(text, ok) {
  const el = $("manual-msg");
  el.textContent = text;
  el.className = "manual-msg " + (ok ? "ok" : "err");
  setTimeout(() => { el.textContent = ""; el.className = "manual-msg"; }, 6000);
}

async function forceOrder(side) {
  const lots = parseFloat($("c-lots").value);
  const tp = parseFloat($("c-tp").value);
  const sl = parseFloat($("c-sl").value);
  const label = side === "long" ? "COMPRA" : "VENTA";
  if (!confirm(`¿Ejecutar ${label} manual de ${lots} lotes (SL ${sl} / TP ${tp} pips)?`)) return;
  const r = await postJSON(`/api/manual/${side}`, { lots, sl_pips: sl, tp_pips: tp });
  showManualMsg(r.ok ? `Orden ${label} enviada (${fmt(r.units, 0)} unidades)` : `Error: ${r.error}`, r.ok);
  refreshLogs();
}
$("btn-force-buy").addEventListener("click", () => forceOrder("long"));
$("btn-force-sell").addEventListener("click", () => forceOrder("short"));

$("btn-close-all").addEventListener("click", async () => {
  if (!confirm("¿Cerrar TODAS las posiciones abiertas a mercado?")) return;
  const r = await postJSON("/api/close-all");
  showManualMsg(r.closed ? `${r.closed} posición(es) cerrada(s)` : "No había posiciones", true);
  refreshLogs();
});

$("positions-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-close]");
  if (!btn) return;
  if (!confirm("¿Cerrar esta posición a mercado?")) return;
  const r = await postJSON(`/api/close/${btn.dataset.close}`);
  showManualMsg(r.ok ? "Cierre enviado" : `Error: ${r.error}`, r.ok);
  refreshLogs();
});

$("btn-save-settings").addEventListener("click", async () => {
  const payload = {
    bb_period: +$("s-bb_period").value,
    bb_std: +$("s-bb_std").value,
    atr_period: +$("s-atr_period").value,
    sl_atr_mult: +$("s-sl_atr_mult").value,
    risk_per_trade: +$("s-risk_per_trade").value / 100,
    daily_loss_limit: +$("s-daily_loss_limit").value / 100,
    max_trades_per_day: +$("s-max_trades_per_day").value,
    max_spread_pips: +$("s-max_spread_pips").value,
    fixed_units: +$("s-fixed_units").value,
  };
  const r = await postJSON("/api/settings", payload);
  const msg = $("settings-msg");
  if (r.ok) {
    msg.textContent = "✓ Guardado — aplica desde la próxima vela.";
    msg.className = "hint ok";
    await refreshSettings();
    refreshCandles();
  } else {
    msg.textContent = "Error al guardar";
    msg.className = "hint";
  }
  setTimeout(() => { msg.textContent = "Los cambios aplican desde la próxima vela."; msg.className = "hint"; }, 5000);
});

/* ================= init ================= */
async function init() {
  connectWS();
  try { renderStatus(await getJSON("/api/status")); } catch {}
  try { renderPositions(await getJSON("/api/positions")); } catch {}
  await Promise.allSettled([refreshCandles(), refreshTrades(), refreshLogs(), refreshSettings()]);
  setInterval(async () => { try { renderStatus(await getJSON("/api/status")); } catch {} }, 15000);
}
init();
