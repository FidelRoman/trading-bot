"""Contrato entre la politica entrenada con torch y produccion con NumPy."""
from __future__ import annotations

import numpy as np
import pytest

from tradingbot.config import PpoParams
from tradingbot.rl.export import export_policy, load_numpy_policy
from tradingbot.rl.ppo import PPOAgent


def test_numpy_coincide_con_torch_en_mil_observaciones(tmp_path):
    agent = PPOAgent(
        observation_size=53,
        action_size=2,
        params=PpoParams(hidden_sizes=(256, 256), seed=37),
    )
    # Los pesos finales arrancan en cero. Alterarlos comprueba el forward real,
    # no solo que ambas implementaciones devuelven 0.5 por casualidad.
    rng = np.random.default_rng(91)
    for parameter in agent.policy.parameters():
        parameter.data.copy_(
            __import__("torch").as_tensor(
                rng.normal(0.0, 0.08, size=tuple(parameter.shape)), dtype=parameter.dtype
            )
        )

    observations = rng.normal(size=(1_000, 53)).astype(np.float32)
    artifact = export_policy(agent, tmp_path / "policy.npz")
    numpy_policy = load_numpy_policy(artifact)

    torch_actions = np.stack([agent.act(obs, deterministic=True) for obs in observations])
    numpy_actions = numpy_policy.act(observations)

    assert numpy_actions.shape == (1_000, 2)
    assert np.allclose(numpy_actions, torch_actions, atol=1e-6, rtol=1e-6)


def test_numpy_rechaza_inferencia_estocastica(tmp_path):
    agent = PPOAgent(5, params=PpoParams(hidden_sizes=(8, 8)))
    policy = load_numpy_policy(export_policy(agent, tmp_path / "policy.npz"))

    with pytest.raises(ValueError, match="determinista"):
        policy.act(np.zeros(5, dtype=np.float32), deterministic=False)


def test_carga_rechaza_artefacto_incompleto(tmp_path):
    path = tmp_path / "policy.npz"
    np.savez(path, W1=np.zeros((2, 2)))

    with pytest.raises(ValueError, match="incompleto"):
        load_numpy_policy(path)
