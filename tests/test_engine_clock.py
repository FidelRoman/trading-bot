"""El reloj del bot: quién fija el timeframe y de dónde sale la frontera de vela.

Las velas de FXCM no caen en múltiplos exactos desde la época —las H4 abren a
01:00/05:00/09:00 UTC y las diarias a las 21:00—, así que la frontera se toma de
las marcas que devuelve el bróker y no de aritmética sobre el reloj.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tradingbot.config import INSTRUMENT_SEEDS, load_settings
from tradingbot.engine import BotEngine, tf_seconds
from tradingbot.store import Store

UTC = timezone.utc


class BrokerConVelas:
    """Devuelve velas en las marcas reales de FXCM y cuenta las consultas."""

    connected = True

    def __init__(self, marcas, spec=INSTRUMENT_SEEDS["EUR/USD"]):
        self.spec = spec
        self.instrument = spec.symbol
        self.marcas = list(marcas)
        self.consultas = 0

    def get_candles(self, count=250, date_from=None, date_to=None,
                    timeframe="h1", symbol=None):
        self.consultas += 1
        idx = pd.Index(self.marcas, name="time")
        return pd.DataFrame(
            {"open": 1.10, "high": 1.11, "low": 1.09, "close": 1.10, "volume": 100},
            index=idx,
        )


def make_engine(tmp_path, broker):
    eng = BotEngine(broker, Store(tmp_path / "clock.db"), load_settings())
    return eng


def marcas_h4(dia, n=6):
    """FXCM abre las H4 a 01:00, 05:00, 09:00… no a 00:00/04:00/08:00."""
    base = datetime(2026, 8, dia, 1, 0, tzinfo=UTC)
    return [base + timedelta(hours=4 * i) for i in range(n)]


# -- segundos por vela ----------------------------------------------------

def test_d1_es_un_timeframe_conocido():
    assert tf_seconds("d1") == 86_400
    assert tf_seconds("H4") == 4 * 3600


def test_un_timeframe_desconocido_no_cae_a_quince_minutos():
    """Caer a 15 min en silencio haría latir el bot creyéndose diario."""
    with pytest.raises(ValueError, match="timeframe desconocido"):
        tf_seconds("w1")


# -- quién fija el timeframe ---------------------------------------------

def test_sin_modelo_manda_el_ajuste(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    eng = make_engine(tmp_path, BrokerConVelas([]))
    eng.update_settings({"active_strategy": "fsrppo", "timeframe": "h4"})

    assert eng.effective_timeframe() == "h4"
    assert eng.status()["timeframe_source"] == "ajuste"


def test_con_modelo_activo_manda_el_modelo(tmp_path, monkeypatch):
    """Darle al agente velas de otro tamaño invalidaría sus pesos en silencio."""
    from tradingbot.rl import registry as registry_mod
    from tradingbot.rl.registry import ModelRegistry

    from test_model_registry import guarda

    modelos = tmp_path / "models"
    monkeypatch.setattr(registry_mod, "MODELS_DIR", modelos)
    reg = ModelRegistry(modelos)
    guarda(reg, "euro-d1", "EUR/USD")           # registro_falso entrena en h1
    meta = reg.path_for("euro-d1") / "meta.json"
    meta.write_text(meta.read_text().replace('"timeframe": "h1"', '"timeframe": "d1"'))
    reg.activate("euro-d1")

    eng = make_engine(tmp_path, BrokerConVelas([]))
    eng.update_settings({"active_strategy": "fsrppo", "timeframe": "m15"})

    assert eng.effective_timeframe() == "d1"
    estado = eng.status()
    assert estado["timeframe"] == "d1"
    assert estado["timeframe_setting"] == "m15"
    assert estado["timeframe_source"] == "modelo"


def test_las_estrategias_clasicas_siguen_con_el_ajuste(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod
    from tradingbot.rl.registry import ModelRegistry

    from test_model_registry import guarda

    modelos = tmp_path / "models"
    monkeypatch.setattr(registry_mod, "MODELS_DIR", modelos)
    reg = ModelRegistry(modelos)
    guarda(reg, "euro-1", "EUR/USD")
    reg.activate("euro-1")

    eng = make_engine(tmp_path, BrokerConVelas([]))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "m30"})

    assert eng.effective_timeframe() == "m30"


# -- de dónde sale la frontera -------------------------------------------

def test_la_frontera_h4_es_la_de_fxcm_no_la_del_reloj(tmp_path, monkeypatch):
    """Regresión: con epoch%4h salía 00:00/04:00/08:00, que no existen."""
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    marcas = marcas_h4(10)                       # 01:00, 05:00, 09:00, 13:00, 17:00, 21:00
    eng = make_engine(tmp_path, BrokerConVelas(marcas))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "h4"})

    # 18:30 UTC: la última vela CERRADA es la que abrió a las 13:00.
    ahora = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)
    boundary, velas = eng._due_boundary(ahora)

    assert boundary == datetime(2026, 8, 10, 13, 0, tzinfo=UTC)
    assert boundary.hour % 4 == 1                # jamás un múltiplo exacto de 4 h
    assert velas.index[-1] == boundary


def test_la_frontera_d1_cae_a_las_21_utc(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    marcas = [datetime(2026, 8, d, 21, 0, tzinfo=UTC) for d in (8, 9, 10)]
    eng = make_engine(tmp_path, BrokerConVelas(marcas))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "d1"})

    # El 11 a las 10:00 la vela que abrió el 10 sigue formándose (cierra el 11 a
    # las 21:00): la última cerrada es la que abrió el 9.
    boundary, _ = eng._due_boundary(datetime(2026, 8, 11, 10, 0, tzinfo=UTC))
    assert boundary == datetime(2026, 8, 9, 21, 0, tzinfo=UTC)

    # Pasadas las 21:00 del 11, la del 10 ya ha cerrado y pasa a ser la buena.
    eng._last_poll = None
    boundary, _ = eng._due_boundary(datetime(2026, 8, 11, 21, 0, 30, tzinfo=UTC))
    assert boundary == datetime(2026, 8, 10, 21, 0, tzinfo=UTC)
    assert boundary.hour == 21                   # nunca medianoche UTC


def test_no_se_procesa_dos_veces_la_misma_vela(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    eng = make_engine(tmp_path, BrokerConVelas(marcas_h4(10)))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "h4"})

    ahora = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)
    boundary, _ = eng._due_boundary(ahora)
    eng._last_processed = boundary

    # Un minuto después no hay vela nueva; y ni siquiera se pregunta al bróker.
    consultas = eng.broker.consultas
    assert eng._due_boundary(ahora + timedelta(minutes=1)) == (None, None)
    assert eng.broker.consultas == consultas


def test_no_se_consulta_al_broker_en_cada_vuelta(tmp_path, monkeypatch):
    """El bucle late cada 5 s; preguntar a FXCM a ese ritmo sería abusivo."""
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    eng = make_engine(tmp_path, BrokerConVelas(marcas_h4(10)))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "h4"})

    arranque = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)
    for i in range(12):                          # un minuto de vueltas de 5 s
        eng._due_boundary(arranque + timedelta(seconds=5 * i))

    assert eng.broker.consultas <= 3             # POLL_SECONDS = 30


def test_una_vela_a_medio_formar_no_se_procesa(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    marcas = marcas_h4(10)
    eng = make_engine(tmp_path, BrokerConVelas(marcas))
    eng.update_settings({"active_strategy": "bollinger", "timeframe": "h4"})

    # 14:00: la vela de 13:00 lleva una hora abierta; la última cerrada es 09:00.
    boundary, _ = eng._due_boundary(datetime(2026, 8, 10, 14, 0, tzinfo=UTC))

    assert boundary == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_un_reinicio_no_repite_la_ultima_vela(tmp_path, monkeypatch):
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")
    store = Store(tmp_path / "clock.db")
    procesada = datetime(2026, 8, 10, 13, 0, tzinfo=UTC)
    store.set_state("last_processed_boundary", procesada.isoformat())

    eng = BotEngine(BrokerConVelas(marcas_h4(10)), store, load_settings())

    assert eng._last_processed == procesada


def test_forex_market_schedule_weekend_detection():
    from tradingbot.engine import forex_market_schedule

    # Miércoles 14:00 UTC -> Abierto
    is_open, msg, next_open = forex_market_schedule(datetime(2026, 8, 12, 14, 0, tzinfo=UTC))
    assert is_open is True
    assert next_open is None

    # Viernes 22:00 UTC -> Cerrado
    is_open, msg, next_open = forex_market_schedule(datetime(2026, 8, 14, 22, 0, tzinfo=UTC))
    assert is_open is False
    assert next_open == datetime(2026, 8, 16, 21, 0, tzinfo=UTC)

    # Sábado 12:00 UTC -> Cerrado
    is_open, msg, next_open = forex_market_schedule(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    assert is_open is False
    assert next_open == datetime(2026, 8, 16, 21, 0, tzinfo=UTC)

    # Domingo 14:00 UTC -> Cerrado
    is_open, msg, next_open = forex_market_schedule(datetime(2026, 8, 16, 14, 0, tzinfo=UTC))
    assert is_open is False
    assert next_open == datetime(2026, 8, 16, 21, 0, tzinfo=UTC)

    # Domingo 22:00 UTC -> Abierto
    is_open, msg, next_open = forex_market_schedule(datetime(2026, 8, 16, 22, 0, tzinfo=UTC))
    assert is_open is True
    assert next_open is None


# -- calendario por clase de activo ---------------------------------------

SABADO = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("asset_class", ["forex", "index", "commodity", "bullion", "treasury"])
def test_la_semana_continua_cubre_los_cfd_sobre_indices_y_materias(asset_class):
    """Índices, materias, metales y bonos cotizan en la ventana de divisas."""
    from tradingbot.engine import market_schedule

    is_open, _, next_open = market_schedule(asset_class, SABADO)
    assert is_open is False
    assert next_open == datetime(2026, 8, 16, 21, 0, tzinfo=UTC)


def test_la_cripto_no_cierra_el_fin_de_semana():
    """El calendario de divisas vetaba en sábado algo que cotiza los 7 días."""
    from tradingbot.engine import market_schedule

    is_open, msg, next_open = market_schedule("crypto", SABADO)
    assert is_open is True
    assert next_open is None
    assert "24/7" in msg


@pytest.mark.parametrize("asset_class", ["share", "other"])
def test_lo_que_no_sigue_la_semana_continua_no_se_veta(asset_class):
    """Una acción depende de su bolsa, no de la ventana de divisas.

    Sin horario fiable no se inventa uno: el filtro de sesión de ``entry_allowed``
    y el propio bróker son los que deciden.
    """
    from tradingbot.engine import market_schedule

    assert market_schedule(asset_class, SABADO)[0] is True


# -- la sesión no depende del calendario ----------------------------------

class BrokerQueCuentaConexiones:
    """Bróker desconectado que registra cada intento de ``connect()``."""

    mode = "fxcm-demo"
    instrument = "EUR/USD"
    spec = INSTRUMENT_SEEDS["EUR/USD"]

    def __init__(self):
        self.connected = False
        self.intentos = 0

    def connect(self):
        self.intentos += 1
        self.connected = True


def test_se_conecta_aunque_el_mercado_este_cerrado(tmp_path, monkeypatch):
    """Sin sesión no hay saldo, ni precios, ni órdenes manuales.

    Condicionar ``connect()`` al calendario dejaba el panel ciego el fin de
    semana y hacía imposible mandar una orden a mano.
    """
    import tradingbot.engine as engine_mod

    broker = BrokerQueCuentaConexiones()
    eng = make_engine(tmp_path, broker)

    monkeypatch.setattr(
        engine_mod, "datetime", _RelojFijo(SABADO), raising=True
    )
    eng._ensure_connected()

    assert broker.intentos == 1
    assert broker.connected is True
    assert eng.market_status(SABADO)[0] is False


class _RelojFijo:
    """``datetime`` con ``now()`` congelado; el resto se delega al real."""

    def __init__(self, momento):
        self._momento = momento

    def now(self, tz=None):
        return self._momento

    def __getattr__(self, name):
        return getattr(datetime, name)
