"""Indicadores de evaluación de la Tabla 2 del paper.

Rentabilidad: CRR, ARR. Riesgo: AVR, MD. Capacidad global: Sharpe, Calmar,
Sortino. Todos se calculan sobre la curva de valor total de la cuenta (TAV).

El paper anualiza con 250 (días de bolsa). Aquí el factor es un parámetro,
porque EUR/USD en H1 tiene ~6.240 barras al año y usar 250 daría cifras
anualizadas sin sentido.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

__all__ = ["BARS_PER_YEAR", "RISK_FREE_RATE", "Metrics", "bars_per_year", "evaluate"]

# Barras por año según timeframe: FX cotiza ~24 h × 5 días × 52 semanas.
# Las claves van en minúscula, como en el resto del proyecto (``TF_FREQ``,
# ``TF_SECONDS``, ``_TF_FXCM``); la búsqueda normaliza para que un "H4" mal
# escrito no acabe anualizando con el factor de H1.
BARS_PER_YEAR = {
    "m5": 74_880,
    "m15": 24_960,
    "m30": 12_480,
    "h1": 6_240,
    "h2": 3_120,
    "h4": 1_560,
    "h8": 780,
    "d1": 260,
}


def bars_per_year(timeframe: str) -> float:
    """Barras por año del timeframe; falla si no se reconoce.

    Devolver un valor por defecto sería peor que fallar: ARR, AVR y Sharpe
    saldrían con un factor equivocado y las cifras parecerían plausibles.
    """
    try:
        return BARS_PER_YEAR[str(timeframe).lower()]
    except KeyError:
        raise ValueError(
            f"timeframe desconocido para anualizar: {timeframe!r} "
            f"(conocidos: {', '.join(BARS_PER_YEAR)})"
        ) from None


# R_f del paper (§Tabla 2).
RISK_FREE_RATE = 0.027855


@dataclass(frozen=True)
class Metrics:
    crr: float          # Cumulative return ratio
    arr: float          # Annualized return ratio
    avr: float          # Annualized volatility ratio
    max_drawdown: float
    sharpe: float
    calmar: float
    sortino: float
    bars: int

    def as_dict(self) -> dict:
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                for k, v in asdict(self).items()}


def _max_drawdown(equity: np.ndarray) -> float:
    """``max_{i<j} (TAV_i − TAV_j)/TAV_i`` — la caída relativa más profunda."""
    peaks = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peaks > 0, (peaks - equity) / peaks, 0.0)
    return float(np.max(drawdowns)) if drawdowns.size else 0.0


def evaluate(
    equity_curve: np.ndarray,
    bars_per_year: float = BARS_PER_YEAR["h1"],
    risk_free: float = RISK_FREE_RATE,
) -> Metrics:
    """Las siete métricas de la Tabla 2 sobre una curva de equity.

    ``equity_curve`` incluye el valor inicial, así que ``n`` barras de operación
    producen ``n + 1`` puntos.
    """
    equity = np.asarray(equity_curve, dtype=float)
    if equity.size < 2:
        raise ValueError("la curva de equity necesita al menos dos puntos")

    periods = equity.size - 1
    initial, final = float(equity[0]), float(equity[-1])

    crr = (final - initial) / initial if initial else float("nan")

    # ARR: el paper usa (1+CRR)^(250/T) − 1. Con CRR ≤ −100 % (cuenta liquidada)
    # la potencia no está definida en los reales.
    if 1.0 + crr <= 0:
        arr = -1.0
    else:
        try:
            arr = float((1.0 + crr) ** (bars_per_year / periods) - 1.0)
        except OverflowError:
            arr = float("inf") if crr > 0 else -1.0

    returns = np.diff(equity) / equity[:-1]
    returns = returns[np.isfinite(returns)]

    avr = float(np.std(returns, ddof=1) * np.sqrt(bars_per_year)) if returns.size > 1 else 0.0
    max_dd = _max_drawdown(equity)

    # El paper escribe min(r_pt − R_f, 0) con R_f anual, pero r_pt es un
    # rendimiento por barra: comparar ambos directamente haría que la desviación
    # bajista fuese casi constante. Se usa el R_f prorrateado por barra.
    threshold = risk_free / bars_per_year
    downside = np.minimum(returns - threshold, 0.0)
    dr = (
        float(np.sqrt(np.sum(downside**2) / (returns.size - 1)) * np.sqrt(bars_per_year))
        if returns.size > 1
        else 0.0
    )

    # Una cuenta que nunca se mueve (el agente no opera) no tiene riesgo entre el
    # que repartir el exceso de retorno: su única "desviación bajista" es el coste
    # de oportunidad frente al activo sin riesgo, y dividir por él da cifras
    # enormes que se leerían como una estrategia desastrosa en vez de como una
    # que no hizo nada. Igual que con AVR = 0, el ratio queda indefinido.
    if avr <= 0:
        dr = 0.0

    excess = arr - risk_free
    return Metrics(
        crr=crr,
        arr=arr,
        avr=avr,
        max_drawdown=max_dd,
        sharpe=excess / avr if avr > 0 else float("nan"),
        calmar=arr / max_dd if max_dd > 0 else float("nan"),
        sortino=excess / dr if dr > 0 else float("nan"),
        bars=periods,
    )
