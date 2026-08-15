"""Modo de ejecución: sim / live, pausa obligatoria en cuenta Real y credenciales.

Determina si las órdenes son simuladas o reales, así que conviene que esté
cubierto por pruebas y no solo por inspección.
"""
import os
import pytest

from tradingbot.config import FxcmCredentials, Settings, load_settings
from tradingbot.mock import MockBroker
from tradingbot.store import Store
from tradingbot.web.app import (
    _make_broker,
    _real_acknowledged,
    _selected_symbol,
    app,
    control,
    execution_mode,
    pause_if_real,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _limpia_entorno(monkeypatch):
    monkeypatch.delenv("MOCK", raising=False)
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    monkeypatch.delenv("FXCM_USER", raising=False)
    monkeypatch.delenv("FXCM_PASS", raising=False)
    monkeypatch.delenv("FXCM_USER_DEMO", raising=False)
    monkeypatch.delenv("FXCM_PASS_DEMO", raising=False)
    monkeypatch.delenv("FXCM_USER_REAL", raising=False)
    monkeypatch.delenv("FXCM_PASS_REAL", raising=False)
    monkeypatch.delenv("FXCM_CONNECTION", raising=False)


def _settings(user="demo", connection="Demo"):
    return Settings(fxcm=FxcmCredentials(user=user, password="x", connection=connection))


# -- resolución del modo -------------------------------------------------------


def test_por_defecto_es_sim_sin_credenciales():
    """El entregable arranca en simulado si no hay credenciales."""
    assert execution_mode() == "sim"


def test_live_si_hay_credenciales(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "algo")
    monkeypatch.setenv("FXCM_PASS", "algo")
    assert execution_mode() == "live"


def test_consentimiento_real_exige_booleano_explicito():
    assert _real_acknowledged({"acknowledge_real": True}) is True
    assert _real_acknowledged({"acknowledge_real": "true"}) is False
    assert _real_acknowledged({}) is False


@pytest.mark.anyio
async def test_api_permite_iniciar_real_bajo_responsabilidad_sin_validar_modelo():
    class StoreFalso:
        def __init__(self):
            self.logs = []

        def log(self, level, message):
            self.logs.append((level, message))

    class EngineFalso:
        def __init__(self):
            self.resumed = False
            self.store = StoreFalso()

        def resume(self):
            self.resumed = True

        def status(self):
            return {"paused": not self.resumed}

    class HubFalso:
        async def broadcast(self, payload):
            return None

    previous = dict(app.state._state)
    try:
        engine = EngineFalso()
        app.state.engine = engine
        app.state.broker = type("BrokerReal", (), {"mode": "fxcm-real"})()
        app.state.hub = HubFalso()

        rejected = await control("resume", {})
        accepted = await control("resume", {"acknowledge_real": True})

        assert rejected["requires_real_ack"] is True
        assert engine.resumed is True
        assert accepted["ok"] is True
        assert any("OPERADOR CONFIRMÓ" in message for _, message in engine.store.logs)
    finally:
        app.state._state.clear()
        app.state._state.update(previous)


def test_mock_gana_a_credenciales(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.setenv("FXCM_USER", "algo")
    assert execution_mode() == "sim"


# -- bróker construido según el modo -------------------------------------------


def test_sim_usa_mock_sin_fuente_real(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    broker = _make_broker(_settings())
    assert isinstance(broker, MockBroker)
    assert getattr(broker, "_source", None) is None


def test_el_broker_simulado_refleja_el_instrumento_elegido(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    store = Store(tmp_path / "sim.db")
    store.set_state("selected_instrument", {"symbol": "XAU/USD"})

    broker = _make_broker(_settings(), store)
    assert broker.instrument == "XAU/USD"
    assert broker.spec.asset_class == "bullion"
    assert broker.spec.pip == 0.01
    assert broker.spec.digits == 2
    assert broker.lot_size == 1
    assert broker.units_for_lots(3) == 3


def test_el_broker_simulado_tolera_un_simbolo_sin_especificacion(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    store = Store(tmp_path / "raro.db")
    store.set_state("selected_instrument", {"symbol": "NOEXISTE"})

    broker = _make_broker(_settings(), store)
    assert broker.spec.symbol == "EUR/USD"


def test_sin_credenciales_cae_en_simulado():
    broker = _make_broker(_settings(user=""))
    assert isinstance(broker, MockBroker)
    assert getattr(broker, "_source", None) is None


def test_live_devuelve_el_broker_fxcm_operativo(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "real")
    broker = _make_broker(_settings())
    assert not isinstance(broker, MockBroker)
    assert broker.read_only is False
    assert broker.instrument == "EUR/USD"
    assert hasattr(broker, "set_position")


def test_live_respeta_el_instrumento_seleccionado(tmp_path, monkeypatch):
    monkeypatch.setenv("FXCM_USER", "real")
    store = Store(tmp_path / "sel.db")
    store.set_state("selected_instrument", {"symbol": "us30"})
    assert _selected_symbol(store) == "US30"
    assert _make_broker(_settings(), store).instrument == "US30"


def test_instrumento_por_defecto_sin_seleccion(tmp_path):
    assert _selected_symbol(None) == "EUR/USD"
    assert _selected_symbol(Store(tmp_path / "vacio.db")) == "EUR/USD"


# -- pausa en cuenta Real ------------------------------------------------------


def test_una_db_nueva_arranca_operando(tmp_path):
    from tradingbot.engine import BotEngine
    store = Store(tmp_path / "nueva.db")
    engine = BotEngine(broker=None, store=store, settings=_settings())
    assert engine.running is True


def _engine(tmp_path, name, connection="Demo"):
    from tradingbot.engine import BotEngine
    settings = _settings(user="algo", connection=connection)
    store = Store(tmp_path / name)
    return BotEngine(broker=None, store=store, settings=settings), settings


def test_arranque_live_en_real_deja_el_bot_pausado(tmp_path, monkeypatch):
    monkeypatch.setenv("FXCM_USER", "algo")
    engine, settings = _engine(tmp_path, "real.db", "Real")
    assert engine.running is True
    assert pause_if_real(engine, settings) is True
    assert engine.running is False
    assert any("pausado" in row["message"].lower() for row in engine.store.recent_logs())


def test_arranque_live_en_real_ya_pausado_no_cambia_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("FXCM_USER", "algo")
    engine, settings = _engine(tmp_path, "real2.db", "Real")
    engine.pause()
    assert pause_if_real(engine, settings) is False
    assert engine.running is False


def test_demo_no_se_pausa_al_arrancar(tmp_path, monkeypatch):
    monkeypatch.setenv("FXCM_USER", "algo")
    engine, settings = _engine(tmp_path, "demo.db", "Demo")
    assert pause_if_real(engine, settings) is False
    assert engine.running is True


# -- credenciales --------------------------------------------------------------

def test_credenciales_no_congelan_os_getenv(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "viejo")
    s = load_settings()
    assert s.fxcm.user == "viejo"

    monkeypatch.setenv("FXCM_USER", "nuevo")
    s2 = load_settings()
    assert s2.fxcm.user == "nuevo"


def test_resolucion_por_conexion_demo(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "base")
    monkeypatch.setenv("FXCM_USER_DEMO", "demouser")
    monkeypatch.setenv("FXCM_USER_REAL", "realuser")
    
    monkeypatch.setenv("FXCM_CONNECTION", "Demo")
    s = load_settings()
    assert s.fxcm.user == "demouser"


def test_resolucion_por_conexion_real(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "base")
    monkeypatch.setenv("FXCM_USER_DEMO", "demouser")
    monkeypatch.setenv("FXCM_USER_REAL", "realuser")
    
    monkeypatch.setenv("FXCM_CONNECTION", "Real")
    s = load_settings()
    assert s.fxcm.user == "realuser"


def test_respaldo_al_par_generico(monkeypatch):
    monkeypatch.setenv("FXCM_USER", "base")
    monkeypatch.setenv("FXCM_CONNECTION", "Demo")
    s = load_settings()
    assert s.fxcm.user == "base"
