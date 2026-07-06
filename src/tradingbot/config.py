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
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    sl_atr_mult: float = 1.5


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


@dataclass(frozen=True)
class Settings:
    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    fxcm: FxcmCredentials = field(default_factory=FxcmCredentials)
    db_path: Path = PROJECT_ROOT / "data" / "tradingbot.db"


def load_settings() -> Settings:
    return Settings()
