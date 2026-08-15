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

from .config import DEFAULT_SPEC, InstrumentSpec


class MockBroker:
    mode = "simulado"

    def __init__(
        self,
        seed: int = 7,
        start_price: float = 1.0850,
        persisted_state=None,
        state_callback=None,
        spec: InstrumentSpec | None = None,
        spread_pips: float = 1.2,
    ):
        self._rng = random.Random(seed)
        self.spec = spec or DEFAULT_SPEC
        self.instrument = self.spec.symbol
        self.spread_pips = spread_pips
        self._lock = threading.Lock()
        self._equity = 10_000.0
        
        self.position = 0            # unidades netas, negativas si corto
        self.entry_price = 0.0
        self.realised = 0.0
        self._fills = []
        self._state_callback = state_callback
        
        self._trades: list[dict] = []
        self._closed: list[dict] = []
        self._next_id = 1
        self.connected = False
        self.last_status = "DISCONNECTED"
        
        self._restore(persisted_state or {})
        
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        n = 15 * 400
        steps = np.random.default_rng(seed).normal(0, 0.00012, n)
        walk = start_price + np.cumsum(steps)
        idx = pd.date_range(end=now, periods=n, freq="1min", tz="UTC")
        self._m1 = pd.Series(walk, index=idx)
        self._price = float(walk[-1])

    @property
    def lot_size(self) -> int:
        return self.spec.lot_size

    def units_for_lots(self, lots: float) -> int:
        return self.normalize_units(int(round(lots * self.lot_size)))

    def _restore(self, state: dict) -> None:
        self._equity = float(state.get("equity", self._equity))
        self.position = int(state.get("position", self.position))
        self.entry_price = float(state.get("entry_price", self.entry_price))
        self.realised = float(state.get("realised", self.realised))
        fills = state.get("fills", [])
        self._fills = list(fills[-100:]) if isinstance(fills, list) else []

    def persistent_state(self) -> dict:
        return {
            "equity": self._equity,
            "position": self.position,
            "entry_price": self.entry_price,
            "realised": self.realised,
            "fills": self._fills[-100:],
        }

    def _persist(self) -> None:
        if self._state_callback is not None:
            self._state_callback(self.persistent_state())

    def connect(self) -> None:
        self.connected = True
        self.last_status = "CONNECTED"

    def disconnect(self) -> None:
        self.connected = False
        self.last_status = "DISCONNECTED"

    def _advance(self) -> None:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        last = self._m1.index[-1]
        while last < now:
            last = last + timedelta(minutes=1)
            self._price += self._rng.gauss(0, 0.00012)
            self._m1.loc[last] = self._price
        self._price += self._rng.gauss(0, 0.00002)
        self._check_sl_tp()

    def current_prices(self) -> dict:
        with self._lock:
            self._advance()
            bid = round(self._price, 5)
            return {
                "bid": bid,
                "ask": round(bid + self.spread_pips * self.spec.pip, 5),
                "spread_pips": self.spread_pips,
                "time": datetime.now(timezone.utc).isoformat(),
            }

    def mid_price(self) -> float:
        return self._price

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

    def floating_pl(self) -> float:
        if not self.position:
            return 0.0
        return ((self._price - self.entry_price) * self.position
                * self.spec.contract_multiplier)

    def _floating_pl_trades(self) -> float:
        return sum(
            (1 if t["side"] == "long" else -1) * (self._price - t["open_rate"])
            * t["units"] * self.spec.contract_multiplier
            for t in self._trades
        )

    def account_info(self) -> dict:
        with self._lock:
            self._advance()
            flotante_net = self.floating_pl()
            flotante_trades = self._floating_pl_trades()
            equity = self._equity + flotante_net + flotante_trades
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
                out.append({**t, "gross_pl": round(
                    d * (self._price - t["open_rate"]) * t["units"]
                    * self.spec.contract_multiplier, 2)})
            
            if self.position:
                out.append({
                    "trade_id": "sim-net",
                    "side": "long" if self.position > 0 else "short",
                    "units": abs(self.position),
                    "open_rate": round(self.entry_price, 5),
                    "open_time": self._fills[0]["time"] if self._fills else None,
                    "gross_pl": round(self.floating_pl(), 2),
                    "open_order_id": "sim-net",
                })
            return out

    def all_open_trades(self) -> list[dict]:
        return self.open_trades()

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

    def normalize_units(self, units: int) -> int:
        minimo = max(int(getattr(self.spec, "min_lot", 1000)), 1)
        return (units // minimo) * minimo

    def open_position(self, side: str, units: int, stop_pips: float, take_profit: float) -> str:
        with self._lock:
            self._advance()
            fill = self._price + (self.spread_pips * self.spec.pip if side == "long" else 0.0)
            tid = f"SIM-{self._next_id}"
            self._next_id += 1
            sl = fill - stop_pips * self.spec.pip if side == "long" else fill + stop_pips * self.spec.pip
            self._trades.append(
                {
                    "trade_id": tid,
                    "open_order_id": tid,
                    "side": side,
                    "units": units,
                    "open_rate": round(fill, 5),
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "stop": round(sl, 5) if stop_pips > 0 else (0.0 if side == "long" else float('inf')),
                    "limit": round(take_profit, 5) if take_profit > 0 else (float('inf') if side == "long" else 0.0),
                }
            )
            return tid

    def open_position_pips(self, side: str, units: int, sl_pips: float, tp_pips: float) -> str:
        with self._lock:
            self._advance()
            ref = self._price + (self.spread_pips * self.spec.pip if side == "long" else 0.0)
        tp = 0
        if tp_pips > 0:
            tp = ref + tp_pips * self.spec.pip if side == "long" else ref - tp_pips * self.spec.pip
        return self.open_position(side, units, sl_pips, tp)

    def close_trade(self, trade_id: str) -> str:
        with self._lock:
            self._advance()
            for t in list(self._trades):
                if t["trade_id"] == trade_id:
                    self._settle(t, self._price)
            if trade_id == "sim-net":
                self.close_position()
            return trade_id

    def set_position(self, target_units: int) -> dict:
        with self._lock:
            target = int(target_units)
            price = self._price
            delta = target - self.position

            if delta == 0:
                return {"traded_units": 0, "price": price, "cost": 0.0,
                        "position": self.position, "realised": 0.0, "order_ids": []}

            cost = (abs(delta) * self.spread_pips * self.spec.pip
                    * self.spec.contract_multiplier)
            realizado = self._realise(target, price)

            self._equity += realizado - cost
            self.realised += realizado - cost
            self._update_entry_price(target, price)
            self.position = target

            fill = {
                "time": datetime.now(timezone.utc).isoformat(),
                "traded_units": delta,
                "price": round(price, 5),
                "cost": round(cost, 4),
                "position": target,
                "realised": round(realizado - cost, 2),
            }
            self._fills.append(fill)
            self._persist()
            return fill

    def _realise(self, target: int, price: float) -> float:
        if self.position == 0:
            return 0.0
        if (target >= 0) == (self.position >= 0):
            cerradas = max(0, abs(self.position) - abs(target))
        else:
            cerradas = abs(self.position)
        if cerradas == 0:
            return 0.0
        direccion = 1 if self.position > 0 else -1
        return (direccion * (price - self.entry_price) * cerradas
                * self.spec.contract_multiplier)

    def _update_entry_price(self, target: int, price: float) -> None:
        if target == 0:
            self.entry_price = 0.0
        elif self.position == 0 or (target >= 0) != (self.position >= 0):
            self.entry_price = price
        elif abs(target) > abs(self.position):
            añadidas = abs(target) - abs(self.position)
            self.entry_price = (
                self.entry_price * abs(self.position) + price * añadidas
            ) / abs(target)

    def close_position(self) -> dict:
        return self.set_position(0)

    def recent_fills(self, limit: int = 50) -> list[dict]:
        return self._fills[-limit:][::-1]

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
        pl = round(
            d * (price - t["open_rate"]) * t["units"]
            * self.spec.contract_multiplier,
            2,
        )
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
