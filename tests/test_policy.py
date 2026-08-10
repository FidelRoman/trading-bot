"""Tests de la inferencia en vivo.

El más importante es el de coherencia entrenamiento/producción: si la política
en vivo no reprodujese barra a barra lo que hace el entorno de entrenamiento, el
backtest y el bot real estarían midiendo cosas distintas y ningún resultado
sería trasladable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.config import FsrParams, PpoParams
from tradingbot.rl.dataset import build_dataset
from tradingbot.rl.env import EnvParams, FxTradingEnv, feature_scale_from_training
from tradingbot.rl.policy import FsrppoPolicy
from tradingbot.rl.ppo import PPOAgent
from tradingbot.rl.registry import ModelRecord, ModelRegistry
from tradingbot.rl.train import train


def velas(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(21)
    close = 1.08 + np.cumsum(rng.standard_normal(n)) * 3e-4
    idx = pd.date_range("2025-03-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": close + 1e-4, "low": close - 1e-4, "close": close}, index=idx
    )


PARAMS_RAPIDOS = FsrParams(window=30, ensemble_size=3)


def test_la_politica_en_vivo_reproduce_al_entorno_de_entrenamiento(tmp_path):
    """Mismas velas y misma posición ⇒ misma decisión, paso a paso."""
    candles = velas(120)
    dataset = build_dataset(candles, PARAMS_RAPIDOS, cache_dir=tmp_path, workers=1)
    env_params = EnvParams(max_units=20_000)

    env = FxTradingEnv(dataset.features, dataset.prices, env_params)
    agente = PPOAgent(env.observation_size, PpoParams(hidden_sizes=(16, 16), seed=4))
    politica = FsrppoPolicy(agente, PARAMS_RAPIDOS, env_params)

    closes = candles["close"].to_numpy(dtype=float)
    desfase = PARAMS_RAPIDOS.window - 1
    observacion = env.reset(start=0)

    for paso in range(15):
        posicion_previa = env.position
        entrada_previa = env.entry_price
        equity_previo = env.equity

        # La misma barra vista desde el bot en vivo: solo el histórico hasta aquí.
        decision = politica.decide(
            closes[: desfase + env.index + 1],
            position=posicion_previa,
            entry_price=entrada_previa,
            equity=equity_previo,
        )

        accion_env = agente.act(observacion, deterministic=True)
        objetivo_env = env.target_position(accion_env)

        assert np.allclose(decision.action, accion_env), f"acciones distintas en el paso {paso}"
        assert decision.target_position == objetivo_env, f"posición distinta en el paso {paso}"
        assert decision.price == pytest.approx(dataset.prices[env.index])

        observacion, _, done, _ = env.step(accion_env)
        if done:
            break


def test_decide_exige_ventana_completa():
    politica = FsrppoPolicy(
        PPOAgent(33, PpoParams(hidden_sizes=(16, 16))), PARAMS_RAPIDOS, EnvParams()
    )
    with pytest.raises(ValueError, match="hacen falta"):
        politica.decide(np.linspace(1.08, 1.09, 10))


def test_decide_clasifica_el_lado_de_la_operacion():
    politica = FsrppoPolicy(
        PPOAgent(33, PpoParams(hidden_sizes=(16, 16), seed=0)), PARAMS_RAPIDOS, EnvParams()
    )
    closes = 1.08 + np.cumsum(np.random.default_rng(1).standard_normal(60)) * 2e-4

    decision = politica.decide(closes, position=0)

    assert decision.side in {"buy", "sell", "hold"}
    assert (decision.delta_units == 0) == (decision.side == "hold")
    assert decision.is_hold == (decision.side == "hold")
    assert decision.target_position == decision.delta_units  # partía de posición 0


def test_la_politica_se_reconstruye_con_los_parametros_con_los_que_se_entreno(tmp_path):
    """Un modelo antiguo debe seguir viendo el mundo como cuando aprendió."""
    candles = velas(200)
    dataset = build_dataset(candles, PARAMS_RAPIDOS, cache_dir=tmp_path, workers=1)
    entrena, evalua = dataset.split(dataset.timestamps[120])

    registro = ModelRegistry(tmp_path / "models")
    env_params = EnvParams(max_units=30_000, spread_pips=0.8)
    ppo = PpoParams(hidden_sizes=(16, 16), iterations=1, episodes_per_iteration=2,
                    steps_per_episode=24, update_epochs=1, seed=0)

    salida = train(entrena, evalua, fsr_params=PARAMS_RAPIDOS, ppo_params=ppo,
                   env_params=env_params, registry=registro)

    recuperada = FsrppoPolicy.from_record(registro, salida.record.run_id)

    assert recuperada.fsr_params == PARAMS_RAPIDOS
    assert recuperada.env_params.feature_scale == pytest.approx(
        feature_scale_from_training(entrena.features)
    )
    assert recuperada.env_params.max_units == env_params.max_units
    assert recuperada.env_params.spread_pips == env_params.spread_pips
    assert recuperada.run_id == salida.record.run_id

    # Y decide exactamente igual que el agente recién entrenado.
    closes = candles["close"].to_numpy(dtype=float)
    contexto = dict(position=1_000, entry_price=1.08, equity=10_500)

    desde_disco = recuperada.decide(closes, **contexto)
    trained_env = EnvParams(**salida.record.env_params)
    en_memoria = FsrppoPolicy(salida.agent, PARAMS_RAPIDOS, trained_env).decide(closes, **contexto)

    assert np.allclose(desde_disco.action, en_memoria.action)
    assert desde_disco.target_position == en_memoria.target_position


def test_sin_modelo_activo_no_hay_politica(tmp_path):
    registro = ModelRegistry(tmp_path)
    assert FsrppoPolicy.load_active(registro) is None


def test_un_modelo_ilegible_no_tumba_el_arranque(tmp_path):
    """Mejor arrancar sin política que no arrancar."""
    registro = ModelRegistry(tmp_path)
    registro.save(
        ModelRecord(
            run_id="run-roto",
            created_at="2026-01-01T00:00:00+00:00",
            instrument="EUR/USD",
            timeframe="H1",
            train_range=["a", "b"],
            test_range=["c", "d"],
            fsr_params={},          # incompleto: no se puede reconstruir FsrParams
            ppo_params={},
            env_params={},
            train_metrics={},
            test_metrics={},
        ),
        PPOAgent(8, PpoParams(hidden_sizes=(16, 16))).state_dict(),
    )
    registro.activate("run-roto")

    assert FsrppoPolicy.load_active(registro) is None
