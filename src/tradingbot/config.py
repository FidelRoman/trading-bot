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

    def __post_init__(self) -> None:
        if self.pip <= 0:
            raise ValueError("pip debe ser positivo")
        if self.min_lot <= 0:
            raise ValueError("min_lot debe ser positivo")
        if self.typical_spread_pips < 0:
            raise ValueError("typical_spread_pips no puede ser negativo")


INSTRUMENTS: dict[str, InstrumentSpec] = {
    "EUR/USD": InstrumentSpec("EUR/USD", pip=0.0001, min_lot=1_000,
                              typical_spread_pips=1.2),
    "GBP/USD": InstrumentSpec("GBP/USD", pip=0.0001, min_lot=1_000,
                              typical_spread_pips=1.5),
    "USD/JPY": InstrumentSpec("USD/JPY", pip=0.01, min_lot=1_000,
                              typical_spread_pips=1.2, quote_currency="JPY"),
    # FXCM permite dimensionar el oro en unidades, no en micro-lotes de 1.000.
    "XAU/USD": InstrumentSpec("XAU/USD", pip=0.01, min_lot=1,
                              typical_spread_pips=35.0),
}


def get_instrument_spec(symbol: str) -> InstrumentSpec:
    """Devuelve una especificación aceptando mayúsculas/minúsculas y ``EURUSD``."""
    normalizado = symbol.strip().upper()
    if "/" not in normalizado and len(normalizado) == 6:
        normalizado = f"{normalizado[:3]}/{normalizado[3:]}"
    try:
        return INSTRUMENTS[normalizado]
    except KeyError as exc:
        disponibles = ", ".join(INSTRUMENTS)
        raise ValueError(f"instrumento desconocido {symbol!r}; disponibles: {disponibles}") from exc


# Compatibilidad para las estrategias históricas. FSRPPO usa InstrumentSpec.
PIP = INSTRUMENTS[INSTRUMENT].pip


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
    min_lot: int = 1000  # micro-lote FXCM


@dataclass(frozen=True)
class FxcmCredentials:
    user: str = os.getenv("FXCM_USER", "")
    password: str = os.getenv("FXCM_PASS", "")
    connection: str = os.getenv("FXCM_CONNECTION", "Demo")
    url: str = os.getenv("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp")

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
