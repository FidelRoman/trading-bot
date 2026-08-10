"""Tests del entorno de trading y de las métricas de la Tabla 2."""
from __future__ import annotations

import numpy as np
import pytest

from tradingbot.config import INSTRUMENTS, PIP
from tradingbot.metrics import evaluate
from tradingbot.rl.env import EnvParams, FxTradingEnv, target_position, transaction_cost

COMPRAR = np.array([0.0, 1.0])
MANTENER = np.array([0.5, 1.0])
VENDER = np.array([1.0, 1.0])


def entorno(precios: list[float], **kwargs) -> FxTradingEnv:
    prices = np.asarray(precios, dtype=float)
    features = np.zeros((len(prices), 4), dtype=np.float32)
    return FxTradingEnv(features, prices, EnvParams(**kwargs))


# -- acción y posición -----------------------------------------------------


def test_mantener_no_mueve_la_posicion_ni_cuesta():
    """El incentivo central del paper: no operar es gratis."""
    env = entorno([1.10] * 5)
    env.step(COMPRAR)
    posicion = env.position
    assert posicion > 0

    _, _, _, info = env.step(MANTENER)
    assert info.traded_units == 0
    assert info.cost == 0.0
    assert env.position == posicion


def test_los_tercios_de_a1_mapean_a_comprar_mantener_vender():
    env = entorno([1.10] * 6)
    assert env.target_position(np.array([0.0, 0.5])) > 0
    assert env.target_position(np.array([0.33, 0.5])) > 0
    assert env.target_position(np.array([1 / 3, 0.5])) == 0   # frontera: mantener
    assert env.target_position(np.array([2 / 3, 0.5])) == 0   # frontera: mantener
    assert env.target_position(np.array([0.7, 0.5])) < 0


def test_a2_gradua_el_tamano_entre_el_minimo_y_el_maximo():
    env = entorno([1.0] * 4, min_trade_amount=1_000, max_trade_amount=10_000, min_lot=1_000)
    assert env.target_position(np.array([0.0, 0.0])) == 1_000
    assert env.target_position(np.array([0.0, 1.0])) == 10_000


@pytest.mark.parametrize(
    ("symbol", "price"),
    [("EUR/USD", 1.10), ("GBP/USD", 1.30), ("USD/JPY", 150.0), ("XAU/USD", 4_000.0)],
)
def test_cada_instrumento_puede_abrir_una_posicion(symbol, price):
    params = EnvParams(instrument=INSTRUMENTS[symbol])

    posicion = target_position(COMPRAR, position=0, price=price, params=params)

    assert posicion != 0
    assert posicion % params.instrument.min_lot == 0


def test_el_coste_usa_el_pip_del_instrumento():
    eurusd = EnvParams(instrument=INSTRUMENTS["EUR/USD"], spread_pips=1.0)
    usdjpy = EnvParams(instrument=INSTRUMENTS["USD/JPY"], spread_pips=1.0)

    assert transaction_cost(1_000, eurusd) == pytest.approx(0.1)
    assert transaction_cost(1_000, usdjpy) == pytest.approx(10.0)


def test_la_exposicion_nunca_supera_el_maximo():
    env = entorno([1.0] * 30, max_units=5_000)
    for _ in range(20):
        _, _, done, _ = env.step(COMPRAR)
        assert abs(env.position) <= 5_000
        if done:
            break


def test_vender_desde_largo_reduce_y_puede_dar_la_vuelta():
    env = entorno([1.0] * 10, max_units=50_000, min_trade_amount=10_000, max_trade_amount=10_000)
    env.step(COMPRAR)
    assert env.position == 10_000
    env.step(VENDER)
    assert env.position == 0
    env.step(VENDER)
    assert env.position == -10_000


# -- recompensa ------------------------------------------------------------


def test_la_recompensa_es_el_pnl_menos_el_spread():
    env = entorno([1.0, 1.001], min_trade_amount=10_000, max_trade_amount=10_000,
                  min_lot=1_000, spread_pips=1.2, max_units=50_000)
    _, reward, _, info = env.step(COMPRAR)

    esperado = 0.001 * 10_000 - 10_000 * 1.2 * PIP
    assert reward == pytest.approx(esperado)
    assert info.cost == pytest.approx(10_000 * 1.2 * PIP)


def test_estar_corto_gana_cuando_el_precio_baja():
    env = entorno([1.0, 0.999], min_trade_amount=10_000, max_trade_amount=10_000,
                  spread_pips=0.0, max_units=50_000)
    _, reward, _, _ = env.step(VENDER)
    assert reward == pytest.approx(0.001 * 10_000)


def test_la_suma_de_recompensas_es_el_cambio_de_equity():
    """Invariante de contabilidad: no se puede crear ni perder dinero por otra vía."""
    rng = np.random.default_rng(5)
    precios = 1.10 + np.cumsum(rng.standard_normal(60)) * 1e-4
    env = entorno(list(precios), max_units=30_000)

    inicial = env.equity
    total = 0.0
    acciones = [COMPRAR, MANTENER, VENDER, MANTENER, COMPRAR]
    for i in range(50):
        _, reward, done, _ = env.step(acciones[i % len(acciones)])
        total += reward
        if done:
            break

    assert env.equity - inicial == pytest.approx(total)


def test_el_episodio_termina_al_arruinarse():
    # Caída sostenida estando largo con exposición máxima.
    precios = list(np.linspace(1.10, 0.80, 200))
    env = entorno(precios, max_units=200_000, min_trade_amount=200_000,
                  max_trade_amount=200_000, ruin_fraction=0.5)

    for _ in range(200):
        _, _, done, _ = env.step(COMPRAR)
        if done:
            break

    assert env.equity <= env.params.initial_equity * 0.5


# -- observación -----------------------------------------------------------


def test_la_observacion_incluye_el_estado_de_la_cuenta():
    env = entorno([1.10] * 5, max_units=10_000)
    assert env.observation_size == 4 + 3

    plano = env.observe()
    assert plano[-3] == pytest.approx(0.0)  # sin posición

    env.step(COMPRAR)
    con_posicion = env.observe()
    assert con_posicion[-3] > 0

    sin_cuenta = entorno([1.10] * 5, include_account_features=False)
    assert sin_cuenta.observation_size == 4


def test_reset_devuelve_la_cuenta_al_estado_inicial():
    env = entorno([1.10] * 20, max_units=30_000)
    for _ in range(5):
        env.step(COMPRAR)

    env.reset(start=3)
    assert env.position == 0
    assert env.equity == env.params.initial_equity
    assert env.index == 3
    assert not env.done


def test_no_se_puede_operar_tras_terminar():
    env = entorno([1.10] * 3)
    env.step(MANTENER)
    env.step(MANTENER)
    assert env.done
    with pytest.raises(RuntimeError):
        env.step(MANTENER)


# -- métricas (Tabla 2) ----------------------------------------------------


def test_el_factor_de_anualizacion_no_admite_timeframes_desconocidos():
    """Un timeframe mal escrito debe fallar, no anualizar con el factor de otro."""
    from tradingbot.metrics import bars_per_year

    assert bars_per_year("h4") == bars_per_year("H4") == 1_560
    assert bars_per_year("h1") == 6_240
    with pytest.raises(ValueError, match="desconocido"):
        bars_per_year("h3")


def test_metricas_sobre_una_curva_conocida():
    # 4 barras, +10 % acumulado.
    curva = np.array([100.0, 110.0, 121.0, 110.0])
    m = evaluate(curva, bars_per_year=3)

    assert m.crr == pytest.approx(0.10)
    # ARR = (1+CRR)^(bars_per_year/T) − 1 con T = 3 periodos ⇒ igual al CRR.
    assert m.arr == pytest.approx(0.10)
    # Máxima caída: de 121 a 110.
    assert m.max_drawdown == pytest.approx(11 / 121)
    assert m.bars == 3


def test_drawdown_de_una_curva_monotona_es_cero():
    m = evaluate(np.array([100.0, 101.0, 102.0, 103.0]))
    assert m.max_drawdown == 0.0
    assert np.isnan(m.calmar)  # dividir por cero no debe explotar


def test_sharpe_penaliza_la_volatilidad():
    """Misma rentabilidad final, más oscilación por el camino ⇒ peor Sharpe."""
    subida = np.linspace(100.0, 110.0, 51)
    oscilante = subida + np.resize([0.0, 3.0, -3.0], 51)
    oscilante[0], oscilante[-1] = subida[0], subida[-1]

    estable = evaluate(subida, bars_per_year=50)
    volatil = evaluate(oscilante, bars_per_year=50)

    assert estable.crr == pytest.approx(volatil.crr)
    assert volatil.avr > estable.avr
    assert volatil.sharpe < estable.sharpe


def test_sin_caidas_el_sortino_y_el_calmar_quedan_indefinidos():
    """Sin desviación bajista ni drawdown no hay riesgo entre el que repartir."""
    subida = evaluate(np.linspace(100.0, 110.0, 51), bars_per_year=50)
    assert np.isnan(subida.sortino)
    assert np.isnan(subida.calmar)

    con_caidas = evaluate(
        np.array([100.0, 105.0, 98.0, 103.0, 110.0]), bars_per_year=4
    )
    assert np.isfinite(con_caidas.sortino)
    assert np.isfinite(con_caidas.calmar)


def test_una_cuenta_liquidada_no_rompe_el_calculo():
    m = evaluate(np.array([100.0, 50.0, 0.0]))
    assert m.crr == pytest.approx(-1.0)
    assert m.arr == -1.0
    assert m.max_drawdown == pytest.approx(1.0)


def test_una_cuenta_que_nunca_opera_no_tiene_ratios():
    """El agente sin entrenar se queda plano; eso no es una estrategia desastrosa.

    Con la curva totalmente plana, la desviación bajista se reduce al coste de
    oportunidad frente al activo sin riesgo, y dividir por ese número minúsculo
    daba un Sortino de -79 que se leía como una catástrofe en vez de como
    "no hizo nada".
    """
    plana = evaluate(np.full(500, 10_000.0), bars_per_year=6_240)

    assert plana.crr == 0.0
    assert plana.avr == 0.0
    assert plana.max_drawdown == 0.0
    assert np.isnan(plana.sharpe)
    assert np.isnan(plana.sortino)
    assert np.isnan(plana.calmar)


def test_la_senal_y_los_rasgos_de_cuenta_estan_en_escalas_comparables():
    """Sin reescalar, la red ignora la señal de precio.

    Las features FSR son rendimientos relativos (σ ≈ 5e-3 en EUR/USD H1) y los
    rasgos de cuenta son del orden de 1. Con esa diferencia de tres órdenes de
    magnitud se midió una política cuya acción variaba 0,0004 entre barras
    completamente distintas: la observación no llegaba a influir en la decisión.
    """
    from tradingbot.rl.env import build_observation

    rng = np.random.default_rng(0)
    señal = rng.standard_normal(50).astype(np.float32) * 5.12e-3  # escala real medida
    params = EnvParams(max_units=20_000)

    obs = build_observation(señal, 10_000, 1.08, 1.09, 10_500.0, params)

    parte_senal, parte_cuenta = obs[:-3], obs[-3:]
    assert parte_senal.std() > 0.1, "la señal llega demasiado plana a la red"
    # Ambas partes deben moverse en el mismo orden de magnitud.
    assert 0.1 < parte_senal.std() / max(abs(parte_cuenta).max(), 1e-9) < 10


def test_el_reescalado_no_altera_la_forma_de_la_senal():
    """Solo cambia la escala: la información relativa se conserva intacta."""
    from tradingbot.rl.env import build_observation

    señal = np.linspace(-0.01, 0.01, 50).astype(np.float32)
    sin_cuenta = EnvParams(include_account_features=False, feature_scale=200.0)
    plana = EnvParams(include_account_features=False, feature_scale=1.0)

    escalada = build_observation(señal, 0, 0.0, 1.08, 10_000.0, sin_cuenta)
    original = build_observation(señal, 0, 0.0, 1.08, 10_000.0, plana)

    assert np.allclose(escalada, original * 200.0)
