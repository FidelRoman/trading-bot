"""Bróker simulado: misma interfaz que FxcmBroker, precios random-walk.

Sirve para (1) desarrollar/ver el dashboard sin credenciales y (2) probar el
pipeline completo del engine sin arriesgar nada. El modo se muestra en la UI
como SIMULADO para que nunca se confunda con la cuenta real.
"""
from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .config import PIP

_SPREAD = 0.00012  # 1.2 pips


class MockBroker:
    mode = "simulado"

    def __init__(self, seed: int = 7, start_price: float = 1.0850):
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._equity = 10_000.0
        self._trades: list[dict] = []
        self._closed: list[dict] = []
        self._next_id = 1
        self.connected = False
        self.last_status = "DISCONNECTED"
        # Serie m1 pre-generada hacia atrás para tener histórico al arrancar
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        n = 15 * 400  # ~400 velas de 15m
        steps = np.random.default_rng(seed).normal(0, 0.00012, n)
        walk = start_price + np.cumsum(steps)
        idx = pd.date_range(end=now, periods=n, freq="1min", tz="UTC")
        self._m1 = pd.Series(walk, index=idx)
        self._price = float(walk[-1])

    # -- sesión ---------------------------------------------------------

    def connect(self) -> None:
        self.connected = True
        self.last_status = "CONNECTED"

    def disconnect(self) -> None:
        self.connected = False
        self.last_status = "DISCONNECTED"

    # -- precios --------------------------------------------------------

    def _advance(self) -> None:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        last = self._m1.index[-1]
        while last < now:
            last = last + timedelta(minutes=1)
            self._price += self._rng.gauss(0, 0.00012)
            self._m1.loc[last] = self._price
        # jitter intraminuto para que el ticker se mueva
        self._price += self._rng.gauss(0, 0.00002)
        self._check_sl_tp()

    def current_prices(self) -> dict:
        with self._lock:
            self._advance()
            bid = round(self._price, 5)
            return {
                "bid": bid,
                "ask": round(bid + _SPREAD, 5),
                "spread_pips": round(_SPREAD / PIP, 2),
                "time": datetime.now(timezone.utc).isoformat(),
            }

    _TF_FREQ = {"m1": "1min", "m5": "5min", "m15": "15min", "m30": "30min",
                "h1": "1h", "h4": "4h", "d1": "1D"}

    def get_candles(self, count: int = 300, date_from=None, date_to=None, timeframe="m15") -> pd.DataFrame:
        freq = self._TF_FREQ.get(timeframe, "15min")
        with self._lock:
            self._advance()
            ohlc = self._m1.resample(freq).agg(["first", "max", "min", "last"]).dropna()
        ohlc.columns = ["open", "high", "low", "close"]
        ohlc["volume"] = 100
        ohlc.index.name = "time"
        return ohlc.tail(count)

    # -- cuenta y trades --------------------------------------------------

    def _floating_pl(self) -> float:
        return sum(
            (1 if t["side"] == "long" else -1) * (self._price - t["open_rate"]) * t["units"]
            for t in self._trades
        )

    def account_info(self) -> dict:
        with self._lock:
            self._advance()
            equity = self._equity + self._floating_pl()
            # margen aproximado 30:1 sobre el nominal abierto
            used = sum(t["units"] for t in self._trades) * self._price / 30
            return {
                "account_id": "SIM-0001",
                "balance": round(self._equity, 2),
                "equity": round(equity, 2),
                "day_pl": 0.0,
                "used_margin": round(used, 2),
                "usable_margin": round(max(equity - used, 0.0), 2),
                "connection": "Simulado",
            }

    def open_trades(self) -> list[dict]:
        with self._lock:
            self._advance()
            out = []
            for t in self._trades:
                d = 1 if t["side"] == "long" else -1
                out.append({**t, "gross_pl": round(d * (self._price - t["open_rate"]) * t["units"], 2)})
            return out

    def closed_trade_info(self, trade_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._closed:
                if t["trade_id"] == trade_id:
                    return {
                        "close_rate": t["close_rate"],
                        "gross_pl": t["gross_pl"],
                        "close_time": t["close_time"],
                    }
        return None

    # -- órdenes ----------------------------------------------------------

    def normalize_units(self, units: int) -> int:
        return (units // 1000) * 1000

    def open_position(self, side: str, units: int, stop_pips: float, take_profit: float) -> str:
        with self._lock:
            self._advance()
            fill = self._price + (_SPREAD if side == "long" else 0.0)
            tid = f"SIM-{self._next_id}"
            self._next_id += 1
            sl = fill - stop_pips * PIP if side == "long" else fill + stop_pips * PIP
            self._trades.append(
                {
                    "trade_id": tid,
                    "open_order_id": tid,
                    "side": side,
                    "units": units,
                    "open_rate": round(fill, 5),
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "stop": round(sl, 5),
                    "limit": round(take_profit, 5),
                }
            )
            return tid

    def open_position_pips(self, side: str, units: int, sl_pips: float, tp_pips: float) -> str:
        with self._lock:
            self._advance()
            ref = self._price + (_SPREAD if side == "long" else 0.0)
        tp = ref + tp_pips * PIP if side == "long" else ref - tp_pips * PIP
        return self.open_position(side, units, sl_pips, tp)

    def close_trade(self, trade_id: str) -> str:
        with self._lock:
            self._advance()
            for t in list(self._trades):
                if t["trade_id"] == trade_id:
                    self._settle(t, self._price)
            return trade_id

    def _check_sl_tp(self) -> None:
        for t in list(self._trades):
            if t["side"] == "long":
                if self._price <= t["stop"]:
                    self._settle(t, t["stop"])
                elif self._price >= t["limit"]:
                    self._settle(t, t["limit"])
            else:
                if self._price >= t["stop"]:
                    self._settle(t, t["stop"])
                elif self._price <= t["limit"]:
                    self._settle(t, t["limit"])

    def _settle(self, t: dict, price: float) -> None:
        d = 1 if t["side"] == "long" else -1
        pl = round(d * (price - t["open_rate"]) * t["units"], 2)
        self._equity += pl
        self._trades.remove(t)
        self._closed.append(
            {
                **t,
                "close_rate": round(price, 5),
                "gross_pl": pl,
                "close_time": datetime.now(timezone.utc).isoformat(),
            }
        )
