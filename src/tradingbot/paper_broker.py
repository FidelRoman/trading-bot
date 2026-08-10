"""Bróker de paper trading con posición neta.

FSRPPO no abre operaciones con SL/TP: gestiona una **posición neta** que ajusta
en cada barra. Este bróker expone esa semántica (`set_position`) sobre la misma
interfaz que usa el resto del bot, ejecutando contra un libro simulado.

Si se le pasa un ``price_source`` (por ejemplo el ``FxcmBroker`` conectado en
solo lectura), los precios y el histórico son **reales** y lo único simulado es
la ejecución. Es la forma honesta de hacer paper trading: el mercado es el de
verdad, el dinero no.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pandas as pd

from .config import PIP
from .mock import MockBroker

__all__ = ["PaperBroker"]


class PaperBroker(MockBroker):
    mode = "paper"

    def __init__(self, price_source=None, initial_equity: float = 10_000.0,
                 spread_pips: float = 1.2, persisted_state=None,
                 state_callback=None, **kwargs):
        super().__init__(**kwargs)
        self._source = price_source
        self._equity = initial_equity
        self.initial_equity = initial_equity
        self.spread_pips = spread_pips

        self.position = 0            # unidades netas, negativas si corto
        self.entry_price = 0.0
        self.realised = 0.0
        self._position_lock = threading.Lock()
        self._fills: list[dict] = []
        self._state_callback = state_callback
        self._restore(persisted_state or {})

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

    # -- conexión y precios: delegan en la fuente real si la hay ------------

    def connect(self) -> None:
        if self._source is not None and not getattr(self._source, "connected", False):
            self._source.connect()
        super().connect()

    def disconnect(self) -> None:
        if self._source is not None:
            self._source.disconnect()
        super().disconnect()

    def current_prices(self) -> dict:
        if self._source is not None:
            return self._source.current_prices()
        return super().current_prices()

    def get_candles(self, count: int = 300, date_from=None, date_to=None,
                    timeframe: str = "h1") -> pd.DataFrame:
        if self._source is not None:
            return self._source.get_candles(count, date_from, date_to, timeframe)
        return super().get_candles(count, date_from, date_to, timeframe)

    # -- posición neta ------------------------------------------------------

    def mid_price(self) -> float:
        prices = self.current_prices()
        return (float(prices["bid"]) + float(prices["ask"])) / 2.0

    def set_position(self, target_units: int) -> dict:
        """Lleva la posición neta a ``target_units`` y devuelve el fill.

        El coste se cobra sobre las unidades que cambian de manos, igual que en
        el entorno de entrenamiento: mantener no cuesta nada.
        """
        with self._position_lock:
            target = int(target_units)
            price = self.mid_price()
            delta = target - self.position

            if delta == 0:
                return {"traded_units": 0, "price": price, "cost": 0.0,
                        "position": self.position, "realised": 0.0}

            cost = abs(delta) * self.spread_pips * PIP
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
        """P&L que se materializa al reducir o dar la vuelta a la posición."""
        if self.position == 0:
            return 0.0
        # Solo cierra lo que se reduce: si se pasa de +5k a -3k, se realizan 5k.
        if (target >= 0) == (self.position >= 0):
            cerradas = max(0, abs(self.position) - abs(target))
        else:
            cerradas = abs(self.position)
        if cerradas == 0:
            return 0.0
        direccion = 1 if self.position > 0 else -1
        return direccion * (price - self.entry_price) * cerradas

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

    # -- estado para la interfaz -------------------------------------------

    def floating_pl(self) -> float:
        if not self.position:
            return 0.0
        return (self.mid_price() - self.entry_price) * self.position

    def account_info(self) -> dict:
        flotante = self.floating_pl()
        return {
            "balance": round(self._equity, 2),
            "equity": round(self._equity + flotante, 2),
            "used_margin": 0.0,
            "gross_pl": round(flotante, 2),
            "currency": "USD",
            "account_id": "PAPER",
        }

    def open_trades(self) -> list[dict]:
        """La posición neta, presentada como una operación abierta."""
        if not self.position:
            return []
        return [
            {
                "trade_id": "paper-net",
                "side": "long" if self.position > 0 else "short",
                "units": abs(self.position),
                "open_rate": round(self.entry_price, 5),
                "open_time": self._fills[0]["time"] if self._fills else None,
                "gross_pl": round(self.floating_pl(), 2),
                "open_order_id": "paper",
            }
        ]

    def recent_fills(self, limit: int = 50) -> list[dict]:
        return self._fills[-limit:][::-1]
