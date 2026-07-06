"""Smoke test de conexión FXCM: login, cuenta, precios y últimas velas.

Uso: uv run python scripts/check_connection.py
Requiere FXCM_USER / FXCM_PASS en .env (conexión Demo por defecto).
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.broker import FxcmBroker
from tradingbot.config import load_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    settings = load_settings()
    broker = FxcmBroker(settings.fxcm)
    print(f"Conectando a FXCM ({settings.fxcm.connection})…")
    broker.connect()
    try:
        info = broker.account_info()
        print("\n=== CUENTA ===")
        for k, v in info.items():
            print(f"  {k:12s} {v}")

        prices = broker.current_prices()
        print("\n=== EUR/USD AHORA ===")
        print(f"  bid {prices['bid']}  ask {prices['ask']}  spread {prices['spread_pips']} pips")

        candles = broker.get_candles(count=5)
        print("\n=== ÚLTIMAS 5 VELAS M15 (bid) ===")
        print(candles.to_string())
        print("\nConexión OK ✅")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
