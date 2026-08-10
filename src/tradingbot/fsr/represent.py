"""FSR — representación por descomposición y reconstrucción (§2.1.4 del paper).

Los tres pasos del paper:

1. CEESMDAN descompone la ventana de precios en IMFs de escalas temporales
   distintas.
2. MRS estima el exponente de Hurst de cada IMF.
3. Se descartan las IMFs con ``H ≤ 0.5`` (ruido de alta frecuencia, "olas") y se
   suman las de ``H > 0.5`` (memoria larga, "mareas").

El residuo final se conserva siempre: es la tendencia monótona que queda tras
extraer todos los modos oscilatorios, el componente de memoria más larga que
existe en la ventana, y MRS no puede estimar nada fiable sobre una curva sin
extremos.

**La función es causal**: solo lee la ventana que termina en la barra evaluada,
nunca datos posteriores. Es la propiedad que impide la fuga de futuro y está
verificada en `tests/test_fsr.py::test_fsr_es_causal`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import FsrParams
from .ceesmdan import ceesmdan
from .mrs import hurst

__all__ = ["FsrResult", "fsr_window", "fsr_features"]


@dataclass(frozen=True)
class FsrResult:
    """Descomposición completa de una ventana, con todo lo que la UI necesita."""

    imfs: np.ndarray        # (K, M) modos intrínsecos
    residue: np.ndarray     # (M,) tendencia restante
    hursts: np.ndarray      # (K,) exponente de Hurst por IMF
    kept: np.ndarray        # (K,) máscara booleana de IMFs conservadas
    signal: np.ndarray      # (M,) señal reconstruida, en unidades de precio
    features: np.ndarray    # (M,) señal lista para la red

    @property
    def discarded_energy(self) -> float:
        """Fracción de la varianza de la ventana que se ha ido como ruido."""
        dropped = self.imfs[~self.kept]
        total = float(np.var(self.imfs.sum(axis=0) + self.residue)) if self.imfs.size else 0.0
        if total <= 0:
            return 0.0
        return float(np.var(dropped.sum(axis=0))) / total if dropped.size else 0.0


def fsr_window(prices: np.ndarray, params: FsrParams | None = None) -> FsrResult:
    """Aplica FSR a una ventana de precios y devuelve la descomposición completa."""
    p = params or FsrParams()
    prices = np.asarray(prices, dtype=float)
    if prices.size < 4:
        raise ValueError(f"ventana demasiado corta para FSR: {prices.size}")

    imfs, residue = ceesmdan(
        prices,
        ensemble_size=p.ensemble_size,
        noise_scale=p.noise_scale,
        n_curves=p.n_curves,
        delta=p.delta,
        max_iter=p.max_iter,
        phi=p.phi,
        max_imfs=p.max_imfs,
        delta_mode=p.delta_mode,
        patience=p.patience,
        seed=p.seed,
    )

    if imfs.size:
        hursts = np.array([hurst(imf, v_min=p.hurst_v_min) for imf in imfs])
        # Un Hurst no estimable (ventana degenerada) se trata como ruido: ante la
        # duda se descarta, que es el sesgo conservador de esta estrategia.
        kept = np.nan_to_num(hursts, nan=0.0) > p.hurst_threshold
    else:
        hursts = np.empty(0)
        kept = np.empty(0, dtype=bool)

    signal = residue + (imfs[kept].sum(axis=0) if kept.any() else 0.0)

    if p.normalize:
        anchor = float(prices[-1])
        features = signal / anchor - 1.0 if anchor != 0 else signal
    else:
        features = signal

    return FsrResult(
        imfs=imfs,
        residue=residue,
        hursts=hursts,
        kept=kept,
        signal=signal,
        features=features,
    )


def fsr_features(prices: np.ndarray, params: FsrParams | None = None) -> np.ndarray:
    """Solo el vector de características — la ruta caliente del precálculo."""
    return fsr_window(prices, params).features
