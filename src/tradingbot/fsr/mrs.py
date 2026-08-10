"""MRS — Modified Rescaled Range analysis (Algoritmo 4 del paper).

R/S clásico de Hurst (1951) con la corrección de sesgo de Anis & Lloyd (1976) y
el factor ``(v − ½)/v`` de Peters (1994), tal como lo recoge Sánchez Granero
et al. (2008) y lo reproduce el Algoritmo 4.

Interpretación en FSR: ``H ≤ 0.5`` = ruido de alta frecuencia sin memoria (se
descarta); ``H > 0.5`` = memoria larga, la tendencia persiste (se conserva).
"""
from __future__ import annotations

import numpy as np
from scipy.special import gammaln

__all__ = ["expected_log_rs", "hurst"]

_LOG_PI = float(np.log(np.pi))


def expected_log_rs(v: int) -> float:
    """``ln E[(R/S)_v]`` bajo la hipótesis nula de independencia.

    Se trabaja en logaritmos porque ``Γ((v−1)/2)`` desborda en doble precisión
    ya para ``v`` de unas pocas centenas.
    """
    k = np.arange(1, v, dtype=float)
    log_sum = float(np.log(np.sqrt((v - k) / k).sum()))
    log_factor = float(np.log((v - 0.5) / v))

    if v <= 340:
        correction = gammaln((v - 1) / 2.0) - 0.5 * _LOG_PI - gammaln(v / 2.0)
    else:
        correction = -0.5 * float(np.log(v * np.pi / 2.0))

    return log_factor + float(correction) + log_sum


def _rescaled_range(block: np.ndarray) -> float | None:
    """``R/S`` de un bloque: rango de la serie de desvíos acumulados / desv. típica."""
    std = block.std()
    if std <= 0:
        return None
    cumulative = np.cumsum(block - block.mean())
    return float((cumulative.max() - cumulative.min()) / std)


def hurst(z: np.ndarray, v_min: int = 2) -> float:
    """Exponente de Hurst de ``z`` por R/S modificado.

    ``v_min`` permite descartar los bloques más cortos, cuya desviación típica es
    demasiado inestable para estimar nada. El paper recorre ``v = 2..⌊N/2⌋``
    (valor por defecto); con ventanas cortas conviene subirlo.

    Devuelve ``nan`` si no hay bloques suficientes para la regresión.
    """
    z = np.asarray(z, dtype=float)
    n = z.size
    log_v: list[float] = []
    log_h: list[float] = []

    for v in range(max(2, v_min), n // 2 + 1):
        blocks = n // v
        if blocks < 1:
            continue
        # "Discard redundant data": se usan solo los I·v primeros puntos.
        trimmed = z[: blocks * v].reshape(blocks, v)
        ratios = [r for r in (_rescaled_range(b) for b in trimmed) if r is not None]
        if not ratios:
            continue
        mean_rs = float(np.mean(ratios))
        if mean_rs <= 0:
            continue
        log_v.append(float(np.log(v)))
        log_h.append(np.log(mean_rs) - expected_log_rs(v) + float(np.log(v)) / 2.0)

    if len(log_v) < 2:
        return float("nan")

    slope, _intercept = np.polyfit(np.asarray(log_v), np.asarray(log_h), 1)
    return float(slope)
