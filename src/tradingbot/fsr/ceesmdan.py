"""CEESMDAN — ESMD completo por ensamblado con ruido adaptativo (Algoritmo 3).

ESMD sufre *mode mixing*: señales de escalas temporales distintas acaban en la
misma IMF. El remedio (heredado de CEEMDAN) es añadir ruido blanco antes de
descomponer — el ruido reparte los extremos de forma uniforme — y promediar
sobre ``J`` realizaciones para cancelarlo.

En cada nivel ``i`` el paper añade ``ξ_{i-1}·G_{i-1}(W_j)``: no ruido crudo, sino
la ``(i-1)``-ésima IMF del ruido, que vive en la misma banda de frecuencia que el
residuo que se está descomponiendo. De ahí lo de *adaptativo*. Para ``i = 1`` no
existe ``G_0`` y se usa el ruido tal cual, como en CEEMDAN.

El paper no fija ``J`` ni ``ξ``. Escalamos el ruido a ``ξ × desviación típica del
residuo`` para que su amplitud relativa sea constante nivel a nivel.
"""
from __future__ import annotations

import numpy as np

from .esmd import esmd, find_extrema, first_imf

__all__ = ["ceesmdan"]


class _NoiseModes:
    """IMFs de cada realización de ruido, descompuestas bajo demanda."""

    def __init__(self, noises: np.ndarray, **kwargs):
        self._noises = noises
        self._kwargs = kwargs
        self._cache: dict[int, np.ndarray] = {}

    def mode(self, j: int, level: int) -> np.ndarray | None:
        """``G_level(W_j)``; ``None`` si el ruido no llega a tantas IMFs."""
        if level <= 0:
            return self._noises[j]
        if j not in self._cache:
            imfs, _ = esmd(self._noises[j], **self._kwargs)
            self._cache[j] = imfs
        imfs = self._cache[j]
        return imfs[level - 1] if level <= len(imfs) else None


def ceesmdan(
    x: np.ndarray,
    ensemble_size: int = 20,
    noise_scale: float = 0.2,
    n_curves: int = 2,
    delta: float = 0.001,
    max_iter: int = 100,
    phi: int = 6,
    max_imfs: int = 12,
    delta_mode: str = "range",
    patience: int = 3,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Descompone ``x`` en IMFs y residuo con ruido adaptativo ensamblado.

    ``seed`` fija las realizaciones de ruido: con la misma semilla la salida es
    determinista, condición necesaria para poder cachear el precálculo de FSR.

    Returns
    -------
    (imfs, residue) con ``imfs`` de forma ``(K, len(x))`` y
    ``sum(imfs) + residue == x`` salvo error de coma flotante.
    """
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    noises = rng.standard_normal((ensemble_size, x.size))
    sift_kwargs = dict(
        n_curves=n_curves,
        delta=delta,
        max_iter=max_iter,
        delta_mode=delta_mode,
        patience=patience,
    )
    noise_modes = _NoiseModes(noises, **sift_kwargs)

    residue = x.copy()
    imfs: list[np.ndarray] = []

    while len(imfs) < max_imfs and find_extrema(residue).size > phi:
        sigma = float(residue.std())
        if sigma <= 0:
            break

        accumulated = np.zeros(x.size)
        for j in range(ensemble_size):
            noise = noise_modes.mode(j, len(imfs))
            if noise is None:
                perturbed = residue
            else:
                spread = float(noise.std())
                scaled = noise / spread if spread > 0 else noise
                perturbed = residue + noise_scale * sigma * scaled
            accumulated += first_imf(perturbed, **sift_kwargs)

        imf = accumulated / ensemble_size
        if not np.isfinite(imf).all():
            break
        imfs.append(imf)
        residue = residue - imf

    stacked = np.asarray(imfs) if imfs else np.empty((0, x.size))
    return stacked, residue
