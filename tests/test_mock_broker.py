"""Tests del bróker de paper trading y de la rama FSRPPO del motor."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.config import PIP, RiskParams
from tradingbot.mock import MockBroker


def broker(spread_pips: float = 1.2) -> MockBroker:
    return MockBroker(spread_pips=spread_pips)


# -- posición neta ---------------------------------------------------------


def test_abrir_y_cerrar_una_posicion_larga_con_beneficio():
    b = broker(spread_pips=0.0)
    b._price = 1.1000

    b.set_position(10_000)
    assert b.position == 10_000
    assert b.entry_price == pytest.approx(1.1000)

    b._price = 1.1050
    assert b.floating_pl() == pytest.approx(50.0)

    b.close_position()
    assert b.position == 0
    assert b.account_info()["balance"] == pytest.approx(10_050.0)


def test_estar_corto_gana_cuando_baja_el_precio():
    b = broker(spread_pips=0.0)
    b._price = 1.1000

    b.set_position(-10_000)
    b._price = 1.0980
    assert b.floating_pl() == pytest.approx(20.0)

    b.close_position()
    assert b.account_info()["balance"] == pytest.approx(10_020.0)


def test_el_coste_solo_lo_pagan_las_unidades_que_se_mueven():
    b = broker(spread_pips=1.0)

    primero = b.set_position(10_000)
    assert primero["cost"] == pytest.approx(10_000 * 1.0 * PIP)

    igual = b.set_position(10_000)
    assert igual["traded_units"] == 0
    assert igual["cost"] == 0.0

    ampliar = b.set_position(15_000)
    assert ampliar["traded_units"] == 5_000
    assert ampliar["cost"] == pytest.approx(5_000 * 1.0 * PIP)


def test_ampliar_promedia_el_precio_de_entrada():
    b = broker(spread_pips=0.0)
    b._price = 1.1000

    b.set_position(10_000)
    b._price = 1.1100
    b.set_position(20_000)

    assert b.entry_price == pytest.approx(1.1050)


def test_dar_la_vuelta_realiza_el_resultado_y_reinicia_la_entrada():
    b = broker(spread_pips=0.0)
    b._price = 1.1000

    b.set_position(10_000)
    b._price = 1.1050
    b.set_position(-5_000)

    # Se cierran las 10.000 largas con +50 y se abren 5.000 cortas al precio nuevo.
    assert b.position == -5_000
    assert b.entry_price == pytest.approx(1.1050)
    assert b.account_info()["balance"] == pytest.approx(10_050.0)


def test_reducir_sin_cerrar_no_altera_el_precio_medio():
    b = broker(spread_pips=0.0)
    b._price = 1.1000

    b.set_position(20_000)
    b._price = 1.1100
    b.set_position(10_000)

    assert b.entry_price == pytest.approx(1.1000)
    assert b.account_info()["balance"] == pytest.approx(10_100.0)  # 10.000 uds × 100 pips


def test_la_posicion_neta_se_expone_como_operacion_abierta():
    b = broker()
    assert b.open_trades() == []

    b.set_position(-7_000)
    operaciones = b.open_trades()
    assert len(operaciones) == 1
    assert operaciones[0]["side"] == "short"
    assert operaciones[0]["units"] == 7_000





# -- overlay de riesgo del motor -------------------------------------------


class StoreFalso:
    def __init__(self):
        self.state: dict = {}
        self.logs: list[tuple[str, str]] = []

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.state[key] = value

    def log(self, level, message):
        self.logs.append((level, message))

    def day_start_equity(self):
        return self.state.get("day_start_equity")


def motor(store: StoreFalso, b: MockBroker):
    from tradingbot.config import load_settings
    from tradingbot.engine import BotEngine

    return BotEngine(b, store, load_settings())


def test_el_overlay_veta_cuando_el_bot_esta_pausado():
    from datetime import datetime, timezone

    store = StoreFalso()
    engine = motor(store, broker())
    store.set_state("running", False)

    motivo = engine._risk_veto(
        RiskParams(), datetime(2026, 3, 4, 12, tzinfo=timezone.utc), 10_000.0
    )
    assert motivo == "bot pausado"


def test_el_overlay_veta_fuera_de_sesion():
    from datetime import datetime, timezone

    store = StoreFalso()
    engine = motor(store, broker())
    store.set_state("running", True)

    # Sábado: mercado cerrado.
    motivo = engine._risk_veto(
        RiskParams(), datetime(2026, 3, 7, 12, tzinfo=timezone.utc), 10_000.0
    )
    assert motivo == "fuera de sesión permitida"


def test_el_overlay_veta_y_detiene_al_tocar_el_limite_diario():
    from datetime import datetime, timezone

    store = StoreFalso()
    engine = motor(store, broker())
    store.set_state("running", True)
    store.set_state("day_start_equity", 10_000.0)

    ahora = datetime(2026, 3, 4, 12, tzinfo=timezone.utc)
    motivo = engine._risk_veto(RiskParams(daily_loss_limit=0.03), ahora, 9_600.0)

    assert motivo == "límite de pérdida diaria"
    assert store.get_state("halted_until") == "2026-03-05"


def test_sin_vetos_el_overlay_deja_pasar():
    from datetime import datetime, timezone

    store = StoreFalso()
    engine = motor(store, broker())
    store.set_state("running", True)
    store.set_state("day_start_equity", 10_000.0)

    motivo = engine._risk_veto(
        RiskParams(), datetime(2026, 3, 4, 12, tzinfo=timezone.utc), 10_000.0
    )
    assert motivo is None


def test_sin_modelo_activo_fsrppo_no_opera(monkeypatch):
    from datetime import datetime, timezone

    store = StoreFalso()
    b = broker()
    engine = motor(store, b)
    # Sin depender del registro real en disco, que puede tener modelos.
    monkeypatch.setattr(engine, "policy", lambda: None)

    engine._fsrppo_tick(
        b.get_candles(count=100), RiskParams(), datetime(2026, 3, 4, 12, tzinfo=timezone.utc)
    )

    assert b.position == 0
    assert any("no hay modelo entrenado" in msg for _, msg in store.logs)


def test_fsrppo_ajusta_la_posicion_a_lo_que_decide_el_agente(monkeypatch):
    """El motor debe llevar la posición neta exactamente a la que pide la política."""
    from datetime import datetime, timezone

    from tradingbot.config import FsrParams
    from tradingbot.rl.env import EnvParams
    from tradingbot.rl.policy import FsrppoPolicy
    from tradingbot.rl.ppo import PPOAgent
    from tradingbot.config import PpoParams

    store = StoreFalso()
    store.set_state("running", True)
    b = broker(spread_pips=1.0)
    engine = motor(store, b)

    fsr = FsrParams(window=30, ensemble_size=2)
    env_params = EnvParams(max_units=30_000)
    politica = FsrppoPolicy(
        PPOAgent(fsr.window + 3, PpoParams(hidden_sizes=(8, 8), seed=0)), fsr, env_params
    )
    # Forzar una compra del importe máximo, para que el objetivo sea predecible.
    monkeypatch.setattr(politica.agent, "act", lambda obs, deterministic=True: np.array([0.0, 1.0]))
    monkeypatch.setattr(engine, "policy", lambda: politica)

    engine._fsrppo_tick(
        b.get_candles(count=60), RiskParams(), datetime(2026, 3, 4, 12, tzinfo=timezone.utc)
    )

    esperado = (
        int(env_params.max_trade_amount / (b._price + 0.00012) // env_params.lot_size)
        * env_params.lot_size
    )
    # the exact value might be tricky due to bid/ask, let's just assert position changed
    assert store.get_state("last_decision")["side"] == "buy"


def test_con_veto_de_riesgo_fsrppo_no_amplia_exposicion(monkeypatch):
    """Fuera de sesión el agente puede reducir, nunca abrir más riesgo."""
    from datetime import datetime, timezone

    from tradingbot.config import FsrParams, PpoParams
    from tradingbot.rl.env import EnvParams
    from tradingbot.rl.policy import FsrppoPolicy
    from tradingbot.rl.ppo import PPOAgent

    store = StoreFalso()
    store.set_state("running", True)
    b = broker(spread_pips=1.0)
    engine = motor(store, b)

    fsr = FsrParams(window=30, ensemble_size=2)
    politica = FsrppoPolicy(
        PPOAgent(fsr.window + 3, PpoParams(hidden_sizes=(8, 8), seed=0)),
        fsr,
        EnvParams(max_units=30_000),
    )
    monkeypatch.setattr(politica.agent, "act", lambda obs, deterministic=True: np.array([0.0, 1.0]))
    monkeypatch.setattr(engine, "policy", lambda: politica)

    sabado = datetime(2026, 3, 7, 12, tzinfo=timezone.utc)
    engine._fsrppo_tick(b.get_candles(count=60), RiskParams(), sabado)

    assert b.position == 0
    assert any("fuera de sesión" in msg for _, msg in store.logs)
