"""Ranking de mercados usando únicamente sus métricas de validación."""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

__all__ = ["rank_markets", "winner_key"]


def _score(row: dict[str, Any]) -> tuple[int, float, float, str, str]:
    validation = row["validation"]
    sharpe = float(validation["median_sharpe"])
    crr = float(validation["median_crr"])
    benchmark = float(validation["benchmark_crr"])
    eligible = isfinite(sharpe) and sharpe > 0 and isfinite(crr) and crr > benchmark
    return (
        int(eligible),
        sharpe if isfinite(sharpe) else float("-inf"),
        crr if isfinite(crr) else float("-inf"),
        str(row["symbol"]),
        str(row["timeframe"]),
    )


def rank_markets(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordena por validación; solo es elegible con Sharpe > 0 y CRR > B&H.

    Cualquier clave de test que el llamador haya añadido se transporta para el
    informe, pero deliberadamente no se consulta aquí. Esto hace comprobable la
    frontera metodológica central del barrido.
    """
    ranked = [dict(candidate) for candidate in candidates]
    ranked.sort(key=_score, reverse=True)
    for index, row in enumerate(ranked, start=1):
        validation = row["validation"]
        sharpe = float(validation["median_sharpe"])
        crr = float(validation["median_crr"])
        benchmark = float(validation["benchmark_crr"])
        row["rank"] = index
        row["eligible"] = (
            isfinite(sharpe) and sharpe > 0 and isfinite(crr) and crr > benchmark
        )
        row["winner"] = False
    for row in ranked:
        if row["eligible"]:
            row["winner"] = True
            break
    return ranked


def winner_key(ranking: list[dict[str, Any]]) -> tuple[str, str]:
    winner = next((row for row in ranking if row.get("winner")), None)
    if winner is None:
        raise ValueError("ningún candidato supera Sharpe > 0 y CRR > Buy & Hold")
    return str(winner["symbol"]), str(winner["timeframe"])
