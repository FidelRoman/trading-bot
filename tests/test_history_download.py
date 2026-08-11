"""Descarga de histórico desde la web.

Va por la sesión que el bróker ya tiene abierta pidiéndole otro símbolo, en
lugar de abrir un segundo login contra FXCM mientras el bot opera.
"""
import pandas as pd
import pytest

from tradingbot.web.training_job import TrainingJob


class StoreFalso:
    def __init__(self):
        self.estado = {}

    def set_state(self, key, value):
        self.estado[key] = value

    def get_state(self, key, default=None):
        return self.estado.get(key, default)


class BrokerFalso:
    """Devuelve una vela por día del rango pedido y anota cada llamada."""

    connected = True

    def __init__(self, instrument="EUR/USD", vacio=False):
        self.instrument = instrument
        self.vacio = vacio
        self.llamadas = []

    def get_candles(self, count=300, date_from=None, date_to=None,
                    timeframe="h1", symbol=None):
        self.llamadas.append({"symbol": symbol, "timeframe": timeframe,
                              "date_from": date_from, "date_to": date_to})
        if self.vacio:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        idx = pd.date_range(date_from, date_to, freq="1D", tz="UTC", inclusive="left")
        return pd.DataFrame(
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10},
            index=pd.Index(idx, name="time"),
        )


@pytest.fixture
def job(tmp_path, monkeypatch):
    from tradingbot.web import training_job as modulo

    monkeypatch.setattr(modulo, "HISTORY_DIR", tmp_path / "history")
    return TrainingJob(StoreFalso())


def test_descarga_escribe_el_csv_con_el_nombre_del_script(job, tmp_path):
    broker = BrokerFalso()

    r = job.run_download(broker=broker, symbol="XAU/USD", timeframe="h4", years=1)

    assert r["status"] == "done"
    assert r["dataset"].startswith("xauusd_h4_")
    assert r["dataset"].endswith(".csv")
    assert (tmp_path / "history" / r["dataset"]).exists()
    assert r["bars"] > 300


def test_pide_el_simbolo_indicado_no_el_del_broker(job):
    """El bot puede estar operando EUR/USD mientras se baja el oro."""
    broker = BrokerFalso(instrument="EUR/USD")

    job.run_download(broker=broker, symbol="XAU/USD", timeframe="h1", years=1)

    assert broker.llamadas
    assert {l["symbol"] for l in broker.llamadas} == {"XAU/USD"}


def test_trocea_el_rango_en_varias_peticiones(job):
    """FXCM acota las velas por llamada, así que el rango va por partes."""
    broker = BrokerFalso()

    job.run_download(broker=broker, symbol="EUR/USD", timeframe="h1", years=2)

    assert len(broker.llamadas) > 4
    # Sin huecos: cada trozo arranca donde acabó el anterior.
    for previa, siguiente in zip(broker.llamadas, broker.llamadas[1:]):
        assert previa["date_to"] == siguiente["date_from"]


def test_sin_velas_lo_dice_con_la_causa_probable(job):
    r = job.run_download(broker=BrokerFalso(vacio=True), symbol="SPX500",
                         timeframe="h1", years=1)

    assert r["status"] == "error"
    assert "suscrito" in r["error"]


def test_broker_desconectado_no_escribe_nada(job, tmp_path):
    broker = BrokerFalso()
    broker.connected = False

    r = job.run_download(broker=broker, symbol="EUR/USD", timeframe="h1", years=1)

    assert r["status"] == "error"
    assert not (tmp_path / "history").exists()


def test_un_solo_trabajo_a_la_vez(job):
    assert job.start_download(broker=BrokerFalso(), symbol="EUR/USD",
                              timeframe="h1", years=1)
    job._claim("training")  # simula un entrenamiento ya en curso
    assert not job.start_download(broker=BrokerFalso(), symbol="EUR/USD",
                                  timeframe="h1", years=1)
