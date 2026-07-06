/* Dashboard BOLLINGER·BOT — datos en vivo vía WebSocket + REST. */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString("es", { minimumFractionDigits: d, maximumFractionDigits: d }));
const fmtPx = (n) => (n == null ? "—" : Number(n).toFixed(5));

/* ---------- charts ---------- */
const chartOpts = {
  layout: { background: { color: "transparent" }, textColor: "#6b7ba3", fontFamily: "JetBrains Mono" },
  grid: {
    vertLines: { color: "rgba(120,160,255,0.06)" },
    horzLines: { color: "rgba(120,160,255,0.06)" },
  },
  rightPriceScale: { borderColor: "rgba(120,160,255,0.15)" },
  timeScale: { borderColor: "rgba(120,160,255,0.15)", timeVisible: true, secondsVisible: false },
  crosshair: {
    vertLine: { color: "rgba(0,229,255,0.35)", labelBackgroundColor: "#0a1122" },
    horzLine: { color: "rgba(0,229,255,0.35)", labelBackgroundColor: "#0a1122" },
  },
  autoSize: true,
};

const candleChart = LightweightCharts.createChart($("chart-candles"), chartOpts);
const candleSeries = candleChart.addCandlestickSeries({
  upColor: "#00ffa3", downColor: "#ff3d71",
  wickUpColor: "#00ffa3", wickDownColor: "#ff3d71",
  borderVisible: false,
  priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
});
const mkBand = (color, width) =>
  candleChart.addLineSeries({ color, lineWidth: width, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
const upperSeries = mkBand("rgba(0,229,255,0.5)", 1);
const lowerSeries = mkBand("rgba(0,229,255,0.5)", 1);
const midSeries = candleChart.addLineSeries({ color: "rgba(139,124,255,0.85)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

const equityChart = LightweightCharts.createChart($("chart-equity"), chartOpts);
const equitySeries = equityChart.addAreaSeries({
  lineColor: "#00e5ff", lineWidth: 2,
  topColor: "rgba(0,229,255,0.28)", bottomColor: "rgba(0,229,255,0.02)",
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});

/* ---------- REST refresh ---------- */
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " → " + r.status);
  return r.json();
}

async function refreshCandles() {
  const { candles, bands } = await getJSON("/api/candles?count=200");
  if (!candles.length) return;
  candleSeries.setData(candles);
  upperSeries.setData(bands.map((b) => ({ time: b.time, value: b.upper })));
  midSeries.setData(bands.map((b) => ({ time: b.time, value: b.mid })));
  lowerSeries.setData(bands.map((b) => ({ time: b.time, value: b.lower })));
}

async function refreshEquity() {
  const rows = await getJSON("/api/equity");
  const seen = new Set();
  const data = [];
  for (const r of rows) {
    const t = Math.floor(new Date(r.ts).getTime() / 1000);
    if (!seen.has(t)) { seen.add(t); data.push({ time: t, value: r.equity }); }
  }
  if (data.length) equitySeries.setData(data);
}

async function refreshTrades() {
  const trades = await getJSON("/api/trades");
  const tbody = document.querySelector("#trades-table tbody");
  $("trades-empty").style.display = trades.length ? "none" : "block";
  tbody.innerHTML = trades
    .map((t) => {
      const pnlCls = (t.pnl ?? 0) >= 0 ? "pnl-pos" : "pnl-neg";
      const dirCls = t.side === "long" ? "dir-long" : "dir-short";
      const dirTxt = t.side === "long" ? "▲ LONG" : "▼ SHORT";
      return `<tr>
        <td class="${dirCls}">${dirTxt}</td>
        <td>${fmt(t.units, 0)}</td>
        <td>${fmtPx(t.entry_rate)}</td>
        <td>${fmtPx(t.exit_rate)}</td>
        <td class="${pnlCls}">${t.pips == null ? "—" : fmt(t.pips, 1)}</td>
        <td class="${pnlCls}">${t.pnl == null ? "—" : fmt(t.pnl)}</td>
        <td>${(t.reason || "—").toUpperCase()}</td>
      </tr>`;
    })
    .join("");
  // Marcadores de entrada sobre el gráfico de velas
  const markers = trades
    .filter((t) => t.entry_time)
    .map((t) => ({
      time: Math.floor(new Date(t.entry_time).getTime() / 1000 / 900) * 900,
      position: t.side === "long" ? "belowBar" : "aboveBar",
      color: t.side === "long" ? "#00ffa3" : "#ff3d71",
      shape: t.side === "long" ? "arrowUp" : "arrowDown",
      text: t.side === "long" ? "L" : "S",
    }))
    .sort((a, b) => a.time - b.time);
  candleSeries.setMarkers(markers);
}

async function refreshLogs() {
  const logs = await getJSON("/api/logs");
  $("log-feed").innerHTML = logs
    .map((l) => `<div class="log-line"><span class="log-ts">${l.ts.replace("T", " ").slice(5, 19)}</span><span class="log-${l.level}">${l.message}</span></div>`)
    .join("");
  $("log-feed").scrollTop = $("log-feed").scrollHeight;
}

/* ---------- estado ---------- */
let lastBid = null, lastAsk = null;

function flash(el, now, prev) {
  el.textContent = fmtPx(now);
  if (prev != null && now !== prev) {
    el.classList.remove("up", "down");
    void el.offsetWidth; // reinicia la animación
    el.classList.add(now > prev ? "up" : "down");
  }
}

function renderTick(msg) {
  flash($("bid"), msg.prices.bid, lastBid);
  flash($("ask"), msg.prices.ask, lastAsk);
  lastBid = msg.prices.bid;
  lastAsk = msg.prices.ask;
  $("spread").textContent = fmt(msg.prices.spread_pips, 1);
  const f = $("floating");
  f.textContent = (msg.floating_pl >= 0 ? "+" : "") + fmt(msg.floating_pl);
  f.className = msg.floating_pl >= 0 ? "pnl-pos" : "pnl-neg";
}

function renderStatus(s) {
  const pill = $("status-pill");
  const btn = $("toggle-btn");
  if (s.paused || s.halted_today) {
    pill.classList.add("paused");
    $("status-text").textContent = s.halted_today ? "LÍMITE DIARIO" : "PAUSADO";
    btn.textContent = "REANUDAR";
    btn.classList.add("resume");
  } else {
    pill.classList.remove("paused");
    $("status-text").textContent = "OPERANDO";
    btn.textContent = "PAUSAR";
    btn.classList.remove("resume");
  }
  const mode = $("mode-chip");
  mode.textContent = (s.mode || "—").toUpperCase();
  mode.className = "chip" + (s.mode === "simulado" ? " warn" : s.mode === "fxcm-demo" ? "" : " ok");
  const conn = $("conn-chip");
  conn.textContent = s.connected ? "CONECTADO" : "SIN CONEXIÓN";
  conn.className = "chip" + (s.connected ? " ok" : " warn");

  $("m-equity").textContent = s.account?.equity != null ? fmt(s.account.equity) : "—";
  const dp = $("m-daypl");
  dp.textContent = (s.daily_pl_pct >= 0 ? "+" : "") + fmt(s.daily_pl_pct) + "%";
  dp.className = "m-val " + (s.daily_pl_pct >= 0 ? "pos" : "neg");
  $("m-winrate").textContent = fmt(s.stats?.win_rate_pct, 1) + "%";
  $("m-pf").textContent = s.stats?.profit_factor == null ? "—" : fmt(s.stats.profit_factor);
  $("m-trades-today").textContent = `${s.trades_today} / ${s.max_trades_per_day}`;
  const pos = $("m-position");
  if (s.open_trade) {
    pos.textContent = (s.open_trade.side === "long" ? "▲ LONG " : "▼ SHORT ") + fmt(s.open_trade.units, 0);
    pos.className = "m-val " + (s.open_trade.side === "long" ? "pos" : "neg");
  } else {
    pos.textContent = "FLAT";
    pos.className = "m-val";
  }
}

/* ---------- WebSocket ---------- */
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
  ws.onclose = () => { clearInterval(ping); $("live-tag").textContent = "RECONECTANDO"; setTimeout(connectWS, 2000); };
  ws.onopen = () => { $("live-tag").textContent = "LIVE"; };
}

/* ---------- control ---------- */
$("toggle-btn").addEventListener("click", async () => {
  const paused = $("status-pill").classList.contains("paused");
  const r = await fetch(`/api/control/${paused ? "resume" : "pause"}`, { method: "POST" });
  const data = await r.json();
  if (data.ok) renderStatus(data.status);
  refreshLogs();
});

/* ---------- init ---------- */
async function init() {
  connectWS();
  try { renderStatus(await getJSON("/api/status")); } catch {}
  await Promise.allSettled([refreshCandles(), refreshEquity(), refreshTrades(), refreshLogs()]);
  setInterval(async () => { try { renderStatus(await getJSON("/api/status")); } catch {} }, 15000);
  setInterval(refreshLogs, 30000);
}
init();
