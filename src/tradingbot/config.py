"""Configuración del bot: credenciales desde .env + parámetros de estrategia."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

INSTRUMENT = "EUR/USD"
TIMEFRAME = "m15"
PIP = 0.0001


@dataclass(frozen=True)
class StrategyParams:
    active_strategy: str = "bollinger"
    timeframe: str = "m15"
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
