from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.download_history import build_parser as download_parser
from scripts.download_history import history_filename, symbol_slug
from tradingbot.broker import FxcmBroker
from tradingbot.config import FxcmCredentials


def test_nombre_de_historico_cumple_el_contrato():
    start = datetime(2020, 8, 9, tzinfo=timezone.utc)
    end = datetime(2026, 8, 9, tzinfo=timezone.utc)
    assert symbol_slug("XAU/USD") == "xauusd"
    assert history_filename("XAU/USD", "H4", start, end) == (
        "xauusd_h4_20200809_20260809.csv"
    )


def test_argumentos_aceptan_listas_y_eliminan_duplicados():
    args = download_parser().parse_args(
        [
            "--symbols",
            "EUR/USD, XAU/USD,EUR/USD",
            "--timeframes",
            "h4,d1",
            "--years",
            "10",
        ]
    )
    assert args.symbols == ["EUR/USD", "XAU/USD"]
    assert args.timeframes == ["h4", "d1"]
    assert args.years == 10


def test_broker_pide_el_historico_del_instrumento_configurado():
    class FakeForexConnect:
        def __init__(self):
            self.calls = []

        def get_history(self, *args):
            self.calls.append(args)
            return pd.DataFrame(
                {
                    "Date": ["2026-08-09T00:00:00Z"],
                    "BidOpen": [4000.0],
                    "BidHigh": [4010.0],
                    "BidLow": [3990.0],
                    "BidClose": [4005.0],
                    "Volume": [10.0],
                }
            )

    broker = FxcmBroker(FxcmCredentials(user="demo", password="demo"), instrument="XAU/USD")
    broker._fx = FakeForexConnect()
    candles = broker.get_candles(count=10, timeframe="h4")

    assert broker._fx.calls[0][0:2] == ("XAU/USD", "H4")
    assert candles.iloc[0]["close"] == 4005.0


def test_broker_read_only_bloquea_todas_las_rutas_de_ordenes():
    broker = FxcmBroker(
        FxcmCredentials(user="real", password="secret", connection="Real"),
        read_only=True,
    )

    with pytest.raises(PermissionError, match="solo lectura"):
        broker.open_position("long", 1_000, 10.0, 1.1)
    with pytest.raises(PermissionError, match="solo lectura"):
        broker.open_position_pips("long", 1_000, 10.0, 20.0)
    with pytest.raises(PermissionError, match="solo lectura"):
        broker.close_trade("trade-id")
