"""Entorno de trading para PPO (§2.3.1–2.3.3 del paper, adaptado a divisas).

El mismo objeto se usa para entrenar, para backtestear y para decidir en vivo:
si el simulador del backtest fuese distinto del de entrenamiento habría dos
verdades y los resultados no serían comparables.

Adaptaciones respecto al paper, que opera acciones long-only con caja:

* **Posición neta con signo.** En FX se puede vender en corto, así que la
  posición ``κ_t`` va de ``−max_units`` a ``+max_units`` en vez de ser un número
  de acciones no negativo. ``a₁`` pasa de "comprar/mantener/vender" a "aumentar
  largo / mantener / aumentar corto", que en una posición contraria equivale a
  reducirla o darle la vuelta.
* **El coste es el spread**, no un impuesto: ``spread × |Δunidades|`` en vez de
  ``α_tax·p_t·μ_t``. Es el coste real de operar divisas y, como en el paper,
  mantener posición no cuesta nada — que es justo lo que desincentiva sobreoperar.
* **Observación ampliada** con tres rasgos de cuenta. El paper observa solo
  precios, pero sin saber qué posición lleva el agente el proceso no es
  markoviano: la misma señal exige acciones opuestas según se esté largo o corto.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import INSTRUMENTS, InstrumentSpec

__all__ = [
    "EnvParams",
    "StepInfo",
    "FxTradingEnv",
    "build_observation",
    "feature_scale_from_training",
    "target_position",
    "transaction_cost",
    "units_for_notional",
]

HOLD_LOW, HOLD_HIGH = 1.0 / 3.0, 2.0 / 3.0


@dataclass(frozen=True)
class EnvParams:
    """Parámetros del entorno. Los importes son los del paper (§2.4.2)."""

    initial_equity: float = 10_000.0
    max_trade_amount: float = 10_000.0   # α_tmax
    min_trade_amount: float = 1_000.0    # α_tmin
    max_units: int = 20_000              # exposición neta máxima (2:1 sobre el capital)
    instrument: InstrumentSpec = field(default_factory=lambda: INSTRUMENTS["EUR/USD"])
    # Overrides de compatibilidad para experimentos antiguos. Si son ``None``,
    # se usan el lote y el spread del InstrumentSpec.
    min_lot: int | None = None
    spread_pips: float | None = None
    include_account_features: bool = True
    # Las features FSR son rendimientos relativos: su desviación típica en
    # EUR/USD H1 es ~5e-3, mientras que los rasgos de cuenta son del orden de 1.
    # Sin reescalar, la red recibe la señal de precio tres órdenes de magnitud
    # por debajo del resto, opera en la zona lineal de las tanh y en la práctica
    # ignora la observación: se midió una política cuya acción variaba 0,0004
    # entre barras completamente distintas. El paper no lo necesita porque
    # alimenta precios de acciones en bruto, que ya son de escala unidad.
    feature_scale: float = 200.0
    # Corta el episodio si la cuenta se hunde: sin esto el agente puede seguir
    # operando con equity negativo, que no es un estado alcanzable en la realidad.
    ruin_fraction: float = 0.5

    def __post_init__(self) -> None:
        # ``asdict`` serializa el InstrumentSpec como dict; aceptar esa forma
        # permite reconstruir modelos guardados sin un decoder paralelo.
        if isinstance(self.instrument, dict):
            object.__setattr__(self, "instrument", InstrumentSpec(**self.instrument))

    @property
    def lot_size(self) -> int:
        return self.instrument.min_lot if self.min_lot is None else self.min_lot

    @property
    def effective_spread_pips(self) -> float:
        return (
            self.instrument.typical_spread_pips
            if self.spread_pips is None
            else self.spread_pips
        )


def feature_scale_from_training(features: np.ndarray) -> float:
    """Escala determinada exclusivamente por las features del tramo de train."""
    valores = np.asarray(features, dtype=np.float64)
    finitos = valores[np.isfinite(valores)]
    if finitos.size == 0:
        return 1.0
    desviacion = float(np.std(finitos))
    if not np.isfinite(desviacion) or desviacion <= np.finfo(np.float32).eps:
        return 1.0
    return 1.0 / desviacion


def build_observation(
    signal: np.ndarray,
    position: int,
    entry_price: float,
    price: float,
    equity: float,
    params: EnvParams,
) -> np.ndarray:
    """Observación que ve la política: señal FSR + estado de la cuenta.

    Vive fuera de la clase a propósito. El bot en vivo no tiene un
    ``FxTradingEnv`` —su posición y su equity los da el bróker— pero **debe**
    construir la observación exactamente igual que durante el entrenamiento. Con
    dos implementaciones paralelas, cualquier cambio en una sería una divergencia
    silenciosa entre entrenamiento y producción.
    """
    # El reescalado va aquí, no dentro de fsr_window, para que la caché de FSR
    # siga siendo válida: es un post-procesado barato de lo ya calculado.
    signal = np.asarray(signal, dtype=np.float32) * params.feature_scale
    if not params.include_account_features:
        return signal

    unrealised = (
        position * (price - entry_price) * params.instrument.contract_multiplier
        if position else 0.0
    )
    account = np.array(
        [
            position / params.max_units,
            unrealised / params.initial_equity,
            equity / params.initial_equity - 1.0,
        ],
        dtype=np.float32,
    )
    return np.concatenate([signal, account])


def target_position(
    action: np.ndarray, position: int, price: float, params: EnvParams
) -> int:
    """Traduce ``(a₁, a₂)`` a la posición neta que quedaría tras operar.

    ``a₁`` reparte el intervalo unidad en tres tercios —aumentar largo, mantener,
    aumentar corto— y ``a₂`` gradúa el importe entre ``α_tmin`` y ``α_tmax``.
    """
    direction, size = float(action[0]), float(np.clip(action[1], 0.0, 1.0))

    if HOLD_LOW <= direction <= HOLD_HIGH:
        return position

    # El paper escribe α_trade = a₂·(α_tmax − α_tmin), que nunca alcanza α_tmax y
    # puede quedar por debajo de α_tmin pese a llamarse mínimo. Se interpreta
    # como interpolación entre ambos límites.
    amount = params.min_trade_amount + size * (params.max_trade_amount - params.min_trade_amount)
    units = units_for_notional(amount, price, params)

    delta = units if direction < HOLD_LOW else -units
    return int(np.clip(position + delta, -params.max_units, params.max_units))


def units_for_notional(amount_usd: float, price: float, params: EnvParams) -> int:
    """Convierte exposición en USD a unidades base y respeta el lote mínimo."""
    base_currency = params.instrument.symbol.split("/", 1)[0]
    if params.instrument.quote_currency == "USD":
        raw_units = amount_usd / (price * params.instrument.contract_multiplier)
    elif base_currency == "USD":
        raw_units = amount_usd / params.instrument.contract_multiplier
    else:
        raise ValueError(
            f"{params.instrument.symbol} requiere un tipo de conversión a USD"
        )
    lot = params.lot_size
    return int(raw_units // lot) * lot


def transaction_cost(traded_units: int, params: EnvParams) -> float:
    """Coste monetario del spread con el pip propio del instrumento."""
    return (
        abs(traded_units)
        * params.effective_spread_pips
        * params.instrument.pip
        * params.instrument.contract_multiplier
    )


@dataclass(frozen=True)
class StepInfo:
    price: float
    next_price: float
    position: int
    traded_units: int
    cost: float
    equity: float


class FxTradingEnv:
    """Interacción barra a barra con el mercado.

    ``features`` es la matriz FSR precalculada ``(N, M)`` y ``prices`` el cierre
    de la barra correspondiente a cada fila. La decisión de la fila ``i`` se
    ejecuta al cierre de esa barra y su recompensa la determina el movimiento
    hasta ``prices[i+1]``, exactamente como la ecuación (11).
    """

    def __init__(
        self,
        features: np.ndarray,
        prices: np.ndarray,
        params: EnvParams | None = None,
    ):
        features = np.asarray(features, dtype=np.float32)
        prices = np.asarray(prices, dtype=float)
        if features.shape[0] != prices.shape[0]:
            raise ValueError(
                f"features y prices desalineados: {features.shape[0]} vs {prices.shape[0]}"
            )
        if features.shape[0] < 2:
            raise ValueError("se necesitan al menos dos barras para poder dar un paso")

        self.features = features
        self.prices = prices
        self.params = params or EnvParams()
        self._start = 0
        self._end = features.shape[0] - 1  # la última barra no tiene "siguiente"
        self.reset()

    # -- espacios ---------------------------------------------------------

    @property
    def observation_size(self) -> int:
        extra = 3 if self.params.include_account_features else 0
        return int(self.features.shape[1]) + extra

    @property
    def action_size(self) -> int:
        return 2

    # -- ciclo de vida ----------------------------------------------------

    def reset(self, start: int = 0, length: int | None = None) -> np.ndarray:
        """Coloca el entorno en la barra ``start`` con la cuenta en su estado inicial."""
        last = self.features.shape[0] - 1
        if not 0 <= start < last:
            raise ValueError(f"start fuera de rango: {start} (máximo {last - 1})")

        self._start = start
        self._end = last if length is None else min(start + length, last)
        self.index = start
        self.equity = self.params.initial_equity
        self.position = 0
        self.entry_price = 0.0
        self.done = False
        return self.observe()

    def observe(self) -> np.ndarray:
        return build_observation(
            self.features[self.index],
            self.position,
            self.entry_price,
            float(self.prices[self.index]),
            self.equity,
            self.params,
        )

    # -- dinámica ---------------------------------------------------------

    def target_position(self, action: np.ndarray) -> int:
        """Posición neta resultante de la acción, dada la posición actual."""
        return target_position(
            action, self.position, float(self.prices[self.index]), self.params
        )

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, StepInfo]:
        """Ejecuta la acción y devuelve ``(obs, recompensa, terminado, info)``."""
        if self.done:
            raise RuntimeError("el episodio ha terminado: hay que llamar a reset()")

        p = self.params
        price = float(self.prices[self.index])
        next_price = float(self.prices[self.index + 1])

        new_position = self.target_position(action)
        traded = new_position - self.position
        cost = transaction_cost(traded, p)

        self._update_entry_price(new_position, price)
        self.position = new_position

        # Ecuación (11): el P&L lo genera toda la posición que se mantiene
        # durante la barra siguiente, y el coste solo lo pagan las unidades
        # que han cambiado de manos.
        reward = (
            (next_price - price) * self.position * p.instrument.contract_multiplier
            - cost
        )
        self.equity += reward

        self.index += 1
        self.done = self.index >= self._end or self.equity <= p.initial_equity * p.ruin_fraction

        info = StepInfo(
            price=price,
            next_price=next_price,
            position=self.position,
            traded_units=traded,
            cost=cost,
            equity=self.equity,
        )
        return self.observe(), float(reward), self.done, info

    def _update_entry_price(self, new_position: int, price: float) -> None:
        """Precio medio de entrada de la posición neta viva."""
        old = self.position
        if new_position == 0:
            self.entry_price = 0.0
        elif old == 0 or np.sign(new_position) != np.sign(old):
            # Apertura, o vuelta de largo a corto: la posición nueva entra entera aquí.
            self.entry_price = price
        elif abs(new_position) > abs(old):
            added = abs(new_position) - abs(old)
            self.entry_price = (self.entry_price * abs(old) + price * added) / abs(new_position)
        # Reducir sin cerrar no cambia el precio medio de lo que queda.
