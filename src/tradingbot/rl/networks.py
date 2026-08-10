"""Redes de política y valor (§2.4.2 del paper).

Dos perceptrones multicapa **separados** —el paper es explícito en que no
comparten parámetros— de dos capas ocultas de 256 neuronas con activación
tanh. La ablación §4.3 justifica esta elección: CNN infraajusta y LSTM/BiLSTM
memorizan el tramo de entrenamiento.

La política emite una distribución **Beta** por dimensión en vez de una normal.
El espacio de acciones es exactamente ``[0,1]²`` y la Beta vive ahí de forma
natural; una normal recortada acumularía masa de probabilidad en los extremos y
sesgaría las acciones "comprar el máximo" y "vender el máximo", que son
justamente las que más mueven la cuenta.
"""
from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.distributions import Beta

__all__ = ["PolicyNet", "ValueNet", "build_mlp"]

# Beta tiene densidad infinita en 0 y 1 cuando α o β < 1: se recortan las
# muestras para que log_prob nunca sea inf.
_EDGE = 1e-6


def build_mlp(input_size: int, hidden_sizes: tuple[int, ...], output_size: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    previous = input_size
    for size in hidden_sizes:
        layers += [nn.Linear(previous, size), nn.Tanh()]
        previous = size
    layers.append(nn.Linear(previous, output_size))
    return nn.Sequential(*layers)


class PolicyNet(nn.Module):
    """π(a|s): una Beta(α, β) independiente por cada componente de la acción."""

    def __init__(self, observation_size: int, action_size: int = 2,
                 hidden_sizes: tuple[int, ...] = (256, 256)):
        super().__init__()
        self.action_size = action_size
        self.body = build_mlp(observation_size, hidden_sizes, 2 * action_size)
        # Arrancar con α = β ≈ 1 (distribución uniforme) equivale a explorar todo
        # el espacio de acciones al principio, sin sesgo hacia comprar o vender.
        final = self.body[-1]
        nn.init.zeros_(final.weight)
        nn.init.zeros_(final.bias)

    def distribution(self, observations: torch.Tensor) -> Beta:
        raw = self.body(observations)
        alpha_raw, beta_raw = raw.chunk(2, dim=-1)
        # softplus(x) + 1 ≥ 1 mantiene la Beta unimodal y sin densidad infinita.
        alpha = nn.functional.softplus(alpha_raw) + 1.0
        beta = nn.functional.softplus(beta_raw) + 1.0
        return Beta(alpha, beta)

    def forward(self, observations: torch.Tensor) -> Beta:
        return self.distribution(observations)

    def act(self, observations: torch.Tensor, deterministic: bool = False):
        """Muestrea una acción y devuelve ``(acción, log-probabilidad)``.

        En inferencia (``deterministic``) se usa la media de la Beta: el bot en
        producción no debe tirar los dados en cada barra.
        """
        dist = self.distribution(observations)
        action = dist.mean if deterministic else dist.sample()
        action = action.clamp(_EDGE, 1.0 - _EDGE)
        return action, dist.log_prob(action).sum(-1)

    def evaluate(self, observations: torch.Tensor, actions: torch.Tensor):
        """``(log π(a|s), entropía)`` para las acciones ya tomadas."""
        dist = self.distribution(observations)
        actions = actions.clamp(_EDGE, 1.0 - _EDGE)
        return dist.log_prob(actions).sum(-1), dist.entropy().sum(-1)


class ValueNet(nn.Module):
    """V(s): estima el retorno descontado desde el estado."""

    def __init__(self, observation_size: int, hidden_sizes: tuple[int, ...] = (256, 256)):
        super().__init__()
        self.body = build_mlp(observation_size, hidden_sizes, 1)

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        return self.body(observations).squeeze(-1)


def as_tensor(array: np.ndarray) -> torch.Tensor:
    return torch.as_tensor(np.asarray(array, dtype=np.float32))
