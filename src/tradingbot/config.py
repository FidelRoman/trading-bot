"""Configuración del bot: credenciales desde .env + parámetros de estrategia."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

INSTRUMENT = "EUR/USD"
TIMEFRAME = "h1"


@dataclass(frozen=True)
class InstrumentSpec:
    """Contrato de mercado usado por sizing, costes y entrenamiento."""

    symbol: str
    pip: float
    min_lot: int
    typical_spread_pips: float
    quote_currency: str = "USD"
    # Fuera de divisas el pip, el lote y el redondeo de precio cambian: las
    # acciones cotizan en unidades de 1 título y los índices llevan menos
    # decimales. Ver tradingbot.instruments.
    asset_class: str = "forex"
    digits: int = 5
    # Multiplicador de contrato: pérdida en el SL = units * distancia * este
    # factor. 1 para divisas y CFD lineales cotizados en la divisa de la cuenta.
    contract_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.pip <= 0:
            raise ValueError("pip debe ser positivo")
        if self.min_lot <= 0:
            raise ValueError("min_lot debe ser positivo")
        if self.typical_spread_pips < 0:
            raise ValueError("typical_spread_pips no puede ser negativo")
        if self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier debe ser positivo")

    @property
    def lot_size(self) -> int:
        """Unidades por lote: 100.000 en divisas, el mínimo operable si no."""
        return 100_000 if self.asset_class == "forex" else max(self.min_lot, 1)


# Semilla de especificaciones conocidas. NO es una lista blanca: el universo real
# lo descubre el worker de la tabla OFFERS de FXCM (ver tradingbot.instruments) y
# se publica en el documento de estado ``instrument_catalog``. Estas entradas son
# el respaldo para trabajar sin catálogo (tests, backtests, primer despliegue).
INSTRUMENT_SEEDS: dict[str, InstrumentSpec] = {
    "EUR/USD": InstrumentSpec("EUR/USD", pip=0.0001, min_lot=1_000,
                              typical_spread_pips=1.2),
    "GBP/USD": InstrumentSpec("GBP/USD", pip=0.0001, min_lot=1_000,
                              typical_spread_pips=1.5),
    "USD/JPY": InstrumentSpec("USD/JPY", pip=0.01, min_lot=1_000,
                              typical_spread_pips=1.2, quote_currency="JPY",
                              digits=3),
    # FXCM permite dimensionar el oro en unidades, no en micro-lotes de 1.000.
    "XAU/USD": InstrumentSpec("XAU/USD", pip=0.01, min_lot=1,
                              typical_spread_pips=35.0, asset_class="bullion",
                              digits=2),
}

#: Alias histórico. Se mantiene porque scripts y UI lo consumen por este nombre.
INSTRUMENTS = INSTRUMENT_SEEDS

#: Especificación por defecto cuando no hay bróker ni catálogo de los que leerla.
DEFAULT_SPEC = INSTRUMENT_SEEDS[INSTRUMENT]


#: Códigos ISO de las divisas que FXCM cotiza al contado, más los metales, que
#: se comportan como divisa en la forma del símbolo. Sirve para decidir si un
#: símbolo de 6 letras es un par (``EURUSD``) o un ticker (``SOYBN``).
CURRENCY_CODES = frozenset((
    "AUD", "CAD", "CHF", "CNH", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF",
    "ILS", "JPY", "MXN", "NOK", "NZD", "PLN", "RUB", "SEK", "SGD", "TRY",
    "USD", "ZAR", "XAU", "XAG", "XPT", "XPD",
))


def normalize_symbol(symbol: str) -> str:
    """Normaliza un símbolo sin imponer forma de par de divisas.

    ``eurusd`` → ``EUR/USD`` (comodidad histórica), pero ``AAPL``, ``US30``,
    ``NAS100`` o ``SOYBN`` se devuelven tal cual. La barra solo se inserta si las
    dos mitades son códigos de divisa conocidos: si no, un ticker de seis letras
    acabaría partido en dos (``AAPLUS`` → ``AAP/LUS``).
    """
    normalizado = str(symbol).strip().upper()
    if "/" not in normalizado and len(normalizado) == 6 and normalizado.isalpha():
        base, quote = normalizado[:3], normalizado[3:]
        if base in CURRENCY_CODES and quote in CURRENCY_CODES:
            return f"{base}/{quote}"
    return normalizado


def get_instrument_spec(symbol: str, catalog: dict | None = None) -> InstrumentSpec:
    """Especificación de un instrumento: primero el catálogo, luego la semilla.

    ``catalog`` es el documento ``instrument_catalog`` publicado por el worker.
    Cuando se pasa, cualquier instrumento que la cuenta FXCM ofrezca es válido;
    sin él solo resuelven las especificaciones semilla.
    """
    normalizado = normalize_symbol(symbol)
    if catalog:
        from .instruments import find_entry, spec_from_entry

        entry = find_entry(catalog, normalizado)
        if entry is not None:
            return spec_from_entry(entry)
    try:
        return INSTRUMENT_SEEDS[normalizado]
    except KeyError as exc:
        disponibles = ", ".join(INSTRUMENT_SEEDS)
        raise ValueError(
            f"instrumento desconocido {symbol!r}; conocidos sin catálogo: {disponibles}"
        ) from exc


# Compatibilidad para los generadores sintéticos de backtest.py y mock.py, que
# simulan explícitamente una serie tipo EUR/USD. El resto del código lee el pip
# del InstrumentSpec activo: un global no puede representar varios instrumentos.
PIP = DEFAULT_SPEC.pip


@dataclass(frozen=True)
class StrategyParams:
    # Bollinger, RSI y Wyckoff se conservan como referencias contra las que medir
    # FSRPPO en la pestaña de backtesting; la estrategia del bot es FSRPPO.
    active_strategy: str = "fsrppo"
    timeframe: str = "h1"
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    # No entrar si (banda sup - banda inf) < este mínimo en pips: con bandas
    # apretadas el TP en la banda media no cubre ni el spread. 0 = sin filtro.
    min_band_width_pips: float = 0.0
    # RSI Strategy:
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    # Wyckoff Strategy:
    wyckoff_range_period: int = 20
    wyckoff_volume_mult: float = 1.5
    wyckoff_tp_mult: float = 2.0



@dataclass(frozen=True)
class FsrParams:
    """Representación de la señal financiera (§2.1 del paper).

    Los valores por defecto son los del paper salvo donde se indica. ``window``
    es ``M`` (50 cierres), ``ensemble_size`` es ``J`` y ``noise_scale`` es ``ξ``
    (el paper no publica ninguno de los dos), ``n_curves`` es ``C``, ``delta``
    es ``δ``, ``max_iter`` es ``D`` y ``phi`` es ``Φ``.
    """

    window: int = 50
    ensemble_size: int = 20
    noise_scale: float = 0.2
    n_curves: int = 2
    delta: float = 0.001
    # δ relativo al rango de la ventana: el δ absoluto del paper está calibrado
    # para precios de acciones, no para divisas. Ver fsr/esmd.py.
    delta_mode: str = "range"
    max_iter: int = 100
    # None = las D=100 pasadas de tamizado del paper (devolviendo siempre el mejor
    # iterado, ver fsr/esmd.py). Bajarlo a 8 acelera ~4x el precálculo a costa de
    # cambiar las features: es un hiperparámetro, no un ajuste cosmético.
    patience: int | None = None
    phi: int = 6
    max_imfs: int = 12
    hurst_threshold: float = 0.5
    hurst_v_min: int = 2
    # Entrega los rendimientos relativos al último cierre en vez del nivel de
    # precio: sin esto la política no generaliza del tramo de train al de test.
    normalize: bool = True
    seed: int = 0

    def cache_key(self) -> str:
        """Huella estable de los parámetros, para invalidar la caché de FSR."""
        import hashlib
        import json

        payload = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class PpoParams:
    """Hiperparámetros de PPO (§2.4.2 y Algoritmo 1 del paper).

    ``iterations`` es ``NI``, ``episodes_per_iteration`` es ``NE`` y
    ``steps_per_episode`` es ``T``.
    """

    gamma: float = 0.99
    gae_lambda: float = 1.0          # λ del paper
    clip_epsilon: float = 0.2        # ε
    entropy_coef: float = 0.01       # c
    learning_rate: float = 1e-5
    hidden_sizes: tuple[int, ...] = (256, 256)
    iterations: int = 200
    episodes_per_iteration: int = 8
    steps_per_episode: int = 256
    # El Algoritmo 1 hace una sola actualización por iteración, pero entonces el
    # cociente π_nueva/π_vieja vale exactamente 1 y el recorte de PPO nunca actúa:
    # se degradaría a gradiente de política a secas. Varias épocas sobre el lote
    # es lo que hace que PPO sea PPO.
    update_epochs: int = 10
    minibatch_size: int = 256
    max_grad_norm: float = 0.5
    seed: int = 0


@dataclass(frozen=True)
class RiskParams:
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.005"))
    daily_loss_limit: float = float(os.getenv("DAILY_LOSS_LIMIT", "0.03"))
    max_trades_per_day: int = int(os.getenv("MAX_TRADES_PER_DAY", "4"))
    max_spread_pips: float = float(os.getenv("MAX_SPREAD_PIPS", "1.5"))
    # Puerta de spread independiente del activo. Un umbral en pips absolutos solo
    # significa algo dentro de un instrumento: 1,5 pips veta el 100% de las
    # acciones y del oro. 2 bps ≈ 1,5 pips de EUR/USD a 1,08, así que el
    # comportamiento en divisas no cambia. Ver strategy.spread_ok.
    max_spread_bps: float = float(os.getenv("MAX_SPREAD_BPS", "2.0"))
    min_lot: int = 1000  # micro-lote FXCM


def _fxcm_user() -> str:
    conn = os.getenv("FXCM_CONNECTION", "Demo")
    if conn == "Demo":
        return os.getenv("FXCM_USER_DEMO") or os.getenv("FXCM_USER", "")
    return os.getenv("FXCM_USER_REAL") or os.getenv("FXCM_USER", "")

def _fxcm_pass() -> str:
    conn = os.getenv("FXCM_CONNECTION", "Demo")
    if conn == "Demo":
        return os.getenv("FXCM_PASS_DEMO") or os.getenv("FXCM_PASS", "")
    return os.getenv("FXCM_PASS_REAL") or os.getenv("FXCM_PASS", "")

@dataclass(frozen=True)
class FxcmCredentials:
    user: str = field(default_factory=_fxcm_user)
    password: str = field(default_factory=_fxcm_pass)
    connection: str = field(default_factory=lambda: os.getenv("FXCM_CONNECTION", "Demo"))
    url: str = field(default_factory=lambda: os.getenv("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp"))

    def validate(self) -> None:
        if not self.user or not self.password:
            raise RuntimeError(
                "Faltan credenciales FXCM: define FXCM_USER y FXCM_PASS en .env "
                "(ver .env.example)"
            )


def _db_path() -> Path:
    """DB separada por modo: los datos simulados no deben mezclarse con los
    de la cuenta FXCM (contaminan equity diario, historial y métricas)."""
    if os.getenv("MOCK") == "1":
        name = "tradingbot-sim.db"
    else:
        conn = os.getenv("FXCM_CONNECTION", "Demo").lower()
        name = f"tradingbot-{conn}.db"
    return PROJECT_ROOT / "data" / name


@dataclass(frozen=True)
class Settings:
    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    fxcm: FxcmCredentials = field(default_factory=FxcmCredentials)
    db_path: Path = field(default_factory=_db_path)


def load_settings() -> Settings:
    return Settings()


def update_env_file(values: dict[str, str], path: Path | None = None) -> None:
    """Actualiza (o crea) claves en el .env preservando el resto de líneas."""
    env_path = path or (PROJECT_ROOT / ".env")
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n")
