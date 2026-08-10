"""Exportacion e inferencia de la politica PPO sin depender de PyTorch.

El artefacto publicado contiene solo los pesos de la red de politica. La red de
valor y los optimizadores son necesarios para entrenar, pero no para decidir en
produccion.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["NumpyPolicy", "export_policy", "load_numpy_policy"]

_EDGE = 1e-6
_FORMAT_VERSION = 1


def _numpy(tensor) -> np.ndarray:
    """Convierte un tensor de torch sin importar torch en este modulo."""
    return tensor.detach().cpu().numpy().astype(np.float32, copy=True)


def export_policy(agent, path: str | Path) -> Path:
    """Exporta la politica de ``PPOAgent`` a un ``policy.npz`` autocontenido.

    ``nn.Linear`` guarda matrices con forma ``(salida, entrada)``. Se
    transponen al exportarlas para que el forward NumPy sea explicitamente
    ``x @ W + b``.
    """
    layers = [layer for layer in agent.policy.body if hasattr(layer, "weight")]
    if len(layers) != 3:
        raise ValueError("la politica exportable debe tener exactamente tres capas lineales")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        format_version=np.asarray(_FORMAT_VERSION, dtype=np.int64),
        observation_size=np.asarray(agent.observation_size, dtype=np.int64),
        action_size=np.asarray(agent.policy.action_size, dtype=np.int64),
        W1=_numpy(layers[0].weight).T,
        b1=_numpy(layers[0].bias),
        W2=_numpy(layers[1].weight).T,
        b2=_numpy(layers[1].bias),
        W3=_numpy(layers[2].weight).T,
        b3=_numpy(layers[2].bias),
    )
    return destination


class NumpyPolicy:
    """Politica Beta determinista evaluada exclusivamente con NumPy."""

    def __init__(
        self,
        W1: np.ndarray,
        b1: np.ndarray,
        W2: np.ndarray,
        b2: np.ndarray,
        W3: np.ndarray,
        b3: np.ndarray,
        observation_size: int,
        action_size: int,
    ) -> None:
        self.W1 = np.asarray(W1, dtype=np.float32)
        self.b1 = np.asarray(b1, dtype=np.float32)
        self.W2 = np.asarray(W2, dtype=np.float32)
        self.b2 = np.asarray(b2, dtype=np.float32)
        self.W3 = np.asarray(W3, dtype=np.float32)
        self.b3 = np.asarray(b3, dtype=np.float32)
        self.observation_size = int(observation_size)
        self.action_size = int(action_size)
        self._validate()

    def _validate(self) -> None:
        expected = (
            self.W1.shape == (self.observation_size, self.b1.size)
            and self.W2.shape == (self.b1.size, self.b2.size)
            and self.W3.shape == (self.b2.size, 2 * self.action_size)
            and self.b3.shape == (2 * self.action_size,)
        )
        if not expected:
            raise ValueError("dimensiones incompatibles en el artefacto policy.npz")

    @staticmethod
    def _softplus(values: np.ndarray) -> np.ndarray:
        # Forma estable: evita overflow para logits positivos grandes.
        return np.maximum(values, 0.0) + np.log1p(np.exp(-np.abs(values)))

    def act(self, observation: np.ndarray, deterministic: bool = True) -> np.ndarray:
        """Devuelve la media de la Beta para una observacion o un lote.

        Produccion siempre es determinista. Rechazar el modo estocastico evita
        que una llamada accidental cambie el comportamiento respecto al bot
        validado.
        """
        if not deterministic:
            raise ValueError("NumpyPolicy solo admite inferencia determinista")

        values = np.asarray(observation, dtype=np.float32)
        single = values.ndim == 1
        if single:
            values = values[None, :]
        if values.ndim != 2 or values.shape[1] != self.observation_size:
            raise ValueError(
                "se esperaban observaciones con ultima dimension "
                f"{self.observation_size}, se recibio {values.shape}"
            )

        hidden1 = np.tanh(values @ self.W1 + self.b1)
        hidden2 = np.tanh(hidden1 @ self.W2 + self.b2)
        raw = hidden2 @ self.W3 + self.b3
        alpha_raw, beta_raw = np.split(raw, 2, axis=-1)
        alpha = self._softplus(alpha_raw) + 1.0
        beta = self._softplus(beta_raw) + 1.0
        action = np.clip(alpha / (alpha + beta), _EDGE, 1.0 - _EDGE).astype(np.float32)
        return action[0] if single else action


def load_numpy_policy(path: str | Path) -> NumpyPolicy:
    """Carga y valida un artefacto creado por :func:`export_policy`."""
    source = Path(path)
    try:
        with np.load(source, allow_pickle=False) as data:
            required = {
                "format_version", "observation_size", "action_size",
                "W1", "b1", "W2", "b2", "W3", "b3",
            }
            missing = required.difference(data.files)
            if missing:
                raise ValueError(f"policy.npz incompleto: faltan {sorted(missing)}")
            version = int(data["format_version"])
            if version != _FORMAT_VERSION:
                raise ValueError(f"version de policy.npz no soportada: {version}")
            return NumpyPolicy(
                data["W1"], data["b1"], data["W2"], data["b2"],
                data["W3"], data["b3"],
                int(data["observation_size"]), int(data["action_size"]),
            )
    except (OSError, KeyError) as exc:
        raise ValueError(f"no se pudo leer {source}: {exc}") from exc
