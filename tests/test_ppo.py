"""Tests de PPO: la maquinaria de aprendizaje y sus invariantes."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from tradingbot.config import PpoParams
from tradingbot.rl.env import EnvParams, FxTradingEnv
from tradingbot.rl.networks import PolicyNet, ValueNet
from tradingbot.rl.ppo import PPOAgent


def entorno_alcista(n: int = 400) -> tuple[FxTradingEnv, float]:
    """Precio que sube siempre y sin spread: el óptimo es largo máximo y mantener."""
    prices = 1.0 + 0.0005 * np.arange(n)
    features = np.tile(np.linspace(-1.0, 1.0, 8), (n, 1)).astype(np.float32)
    params = EnvParams(
        max_units=10_000,
        min_trade_amount=10_000,
        max_trade_amount=10_000,
        spread_pips=0.0,
    )
    optimo = (prices[-1] - prices[0]) * params.max_units
    return FxTradingEnv(features, prices, params), optimo


# -- redes -----------------------------------------------------------------


def test_la_politica_solo_produce_acciones_en_el_cuadrado_unidad():
    politica = PolicyNet(observation_size=6, action_size=2, hidden_sizes=(16, 16))
    observaciones = torch.randn(256, 6)

    acciones, log_probs = politica.act(observaciones)

    assert acciones.shape == (256, 2)
    assert bool((acciones >= 0.0).all() and (acciones <= 1.0).all())
    assert torch.isfinite(log_probs).all()


def test_la_politica_arranca_explorando_de_forma_uniforme():
    """Sin sesgo inicial hacia comprar o vender: la Beta empieza en (1, 1)."""
    politica = PolicyNet(observation_size=6, hidden_sizes=(16, 16))
    dist = politica.distribution(torch.randn(64, 6))
    assert torch.allclose(dist.mean, torch.full_like(dist.mean, 0.5), atol=1e-5)


def test_la_accion_determinista_es_reproducible():
    agente = PPOAgent(observation_size=6, params=PpoParams(hidden_sizes=(16, 16), seed=1))
    observacion = np.zeros(6, dtype=np.float32)

    primera = agente.act(observacion, deterministic=True)
    segunda = agente.act(observacion, deterministic=True)

    assert np.array_equal(primera, segunda)


def test_las_redes_de_politica_y_valor_no_comparten_parametros():
    """El paper lo exige explícitamente en §2.4.2."""
    agente = PPOAgent(observation_size=6, params=PpoParams(hidden_sizes=(16, 16)))
    ids_politica = {id(p) for p in agente.policy.parameters()}
    ids_valor = {id(p) for p in agente.value.parameters()}
    assert ids_politica.isdisjoint(ids_valor)


def test_la_red_de_valor_tiene_la_forma_del_paper():
    valor = ValueNet(observation_size=53, hidden_sizes=(256, 256))
    lineales = [m for m in valor.body if isinstance(m, torch.nn.Linear)]
    assert [m.out_features for m in lineales] == [256, 256, 1]
    assert valor(torch.randn(10, 53)).shape == (10,)


# -- ventaja generalizada --------------------------------------------------


def test_gae_con_lambda_1_es_el_retorno_descontado_menos_el_valor():
    """Con λ = 1 (el valor del paper) GAE se reduce a Monte Carlo."""
    agente = PPOAgent(observation_size=4, params=PpoParams(gae_lambda=1.0, gamma=0.9,
                                                          hidden_sizes=(8, 8)))
    rewards = np.array([1.0, 2.0, 3.0])
    values = np.array([0.5, 0.25, 0.125])

    ventajas, retornos = agente._gae(rewards, values, bootstrap=0.0)

    esperado = []
    for t in range(3):
        descontado = sum(0.9**k * rewards[t + k] for k in range(3 - t))
        esperado.append(descontado - values[t])

    assert ventajas == pytest.approx(np.array(esperado), rel=1e-5)
    assert retornos == pytest.approx(np.array(esperado) + values, rel=1e-5)


def test_gae_usa_el_valor_de_arranque_si_el_episodio_se_trunca():
    agente = PPOAgent(observation_size=4, params=PpoParams(gae_lambda=1.0, gamma=1.0,
                                                          hidden_sizes=(8, 8)))
    sin_bootstrap = agente._gae(np.array([1.0]), np.array([0.0]), bootstrap=0.0)[0]
    con_bootstrap = agente._gae(np.array([1.0]), np.array([0.0]), bootstrap=5.0)[0]
    assert con_bootstrap[0] - sin_bootstrap[0] == pytest.approx(5.0)


# -- aprendizaje -----------------------------------------------------------


def test_ppo_aprende_el_entorno_de_juguete():
    """El test que demuestra que la maquinaria completa funciona.

    En un mercado que solo sube, la política óptima es ponerse largo al máximo y
    mantener. Se usa una tasa de aprendizaje mayor que la del paper (1e-5) para
    que el test dure segundos: lo que se verifica es el mecanismo, no los
    hiperparámetros publicados.
    """
    env, optimo = entorno_alcista()
    params = PpoParams(
        learning_rate=3e-3,
        iterations=40,
        episodes_per_iteration=4,
        steps_per_episode=128,
        update_epochs=6,
        minibatch_size=128,
        seed=0,
    )
    agente = PPOAgent(env.observation_size, params)
    historial = agente.learn(env)

    assert len(historial) == 40
    assert historial[-1].mean_reward > historial[0].mean_reward

    observacion = env.reset(start=0)
    conseguido = 0.0
    while True:
        observacion, recompensa, terminado, info = env.step(agente.act(observacion))
        conseguido += recompensa
        if terminado:
            break

    assert conseguido >= 0.9 * optimo, f"solo alcanzó {100 * conseguido / optimo:.0f}% del óptimo"
    assert info.position == env.params.max_units


def test_el_agente_sobrevive_a_un_lote_con_episodios_truncados():
    """Un episodio que termina por ruina no debe romper el cálculo del lote."""
    prices = np.linspace(1.10, 0.60, 300)
    features = np.zeros((300, 4), dtype=np.float32)
    env = FxTradingEnv(
        features,
        prices,
        EnvParams(max_units=100_000, min_trade_amount=100_000, max_trade_amount=100_000),
    )
    agente = PPOAgent(env.observation_size, PpoParams(hidden_sizes=(16, 16),
                                                      episodes_per_iteration=3,
                                                      steps_per_episode=64,
                                                      update_epochs=2, seed=0))
    historial = agente.learn(env, iterations=2)
    assert all(np.isfinite(s.mean_reward) for s in historial)


def test_el_entrenamiento_es_reproducible_por_semilla():
    """Dos agentes con la misma semilla deben aprender exactamente lo mismo.

    Sin RNG propio, el orden de los minilotes lo marcaría el generador global de
    numpy y el resultado dependería de qué se hubiera ejecutado antes en el
    proceso: los runs dejarían de ser comparables entre sí.
    """
    params = PpoParams(hidden_sizes=(16, 16), episodes_per_iteration=2,
                       steps_per_episode=32, update_epochs=3, seed=11)

    def entrenar() -> np.ndarray:
        env, _ = entorno_alcista(n=120)
        agente = PPOAgent(env.observation_size, params)
        agente.learn(env, iterations=3)
        return agente.act(env.reset(start=0))

    primera = entrenar()
    np.random.seed(999)          # ensuciar el RNG global a propósito
    _ = np.random.random(1000)
    segunda = entrenar()

    assert np.allclose(primera, segunda)


def test_los_pesos_se_guardan_y_se_recuperan():
    env, _ = entorno_alcista(n=120)
    params = PpoParams(hidden_sizes=(16, 16), episodes_per_iteration=2,
                       steps_per_episode=32, update_epochs=2, seed=0)
    agente = PPOAgent(env.observation_size, params)
    agente.learn(env, iterations=2)

    observacion = env.reset(start=0)
    esperado = agente.act(observacion)

    copia = PPOAgent(env.observation_size, params)
    copia.load_state_dict(agente.state_dict())

    assert np.allclose(copia.act(observacion), esperado)
