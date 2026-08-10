"""Construcción y partición temporal del conjunto de datos para FSRPPO.

Une las tres piezas que el entorno necesita —marcas de tiempo, precios y
características FSR— manteniendo la alineación: la fila ``i`` de ``features``
describe la barra que cierra en ``timestamps[i]`` con precio ``prices[i]``, y
solo mira las ``window`` barras que terminan ahí.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..config import FsrParams
from ..fsr.cache import cached_features

__all__ = ["Dataset", "build_dataset"]


@dataclass(frozen=True)
class Dataset:
    timestamps: pd.DatetimeIndex
    prices: np.ndarray
    features: np.ndarray

    def __len__(self) -> int:
        return len(self.prices)

    def __post_init__(self) -> None:
        if not (len(self.timestamps) == len(self.prices) == len(self.features)):
            raise ValueError(
                "dataset desalineado: "
                f"{len(self.timestamps)} marcas, {len(self.prices)} precios, "
                f"{len(self.features)} filas de features"
            )

    def slice(self, start: int, end: int | None = None) -> "Dataset":
        stop = len(self) if end is None else end
        return Dataset(self.timestamps[start:stop], self.prices[start:stop],
                       self.features[start:stop])

    def split(self, train_end: str | pd.Timestamp) -> tuple["Dataset", "Dataset"]:
        """Parte en (train, test) por fecha, sin solapamiento de barras.

        Que la primera ventana de test incluya barras del tramo de train no es
        fuga: en producción esa historia también está disponible al decidir. Lo
        que nunca ocurre es lo contrario —una barra de train mirando al futuro—
        porque FSR es causal.
        """
        limite = pd.Timestamp(train_end)
        if limite.tz is None:
            limite = limite.tz_localize("UTC")

        corte = int(np.searchsorted(self.timestamps.values, limite.to_datetime64(), side="right"))
        if corte < 2 or corte > len(self) - 2:
            raise ValueError(
                f"la fecha de corte {limite:%Y-%m-%d} deja un tramo vacío "
                f"(barra {corte} de {len(self)})"
            )
        return self.slice(0, corte), self.slice(corte)

    def split_three_way(
        self,
        train_ratio: float = 0.60,
        validation_ratio: float = 0.20,
    ) -> tuple["Dataset", "Dataset", "Dataset"]:
        """Parte cronológicamente en train, validación y test sin solapamiento.

        La selección de mercado debe mirar únicamente el segundo tramo. El
        último se devuelve separado para que el llamador pueda mantenerlo
        cerrado hasta haber elegido una sola combinación.
        """
        if not 0 < train_ratio < 1:
            raise ValueError("train_ratio debe estar entre 0 y 1")
        if not 0 < validation_ratio < 1:
            raise ValueError("validation_ratio debe estar entre 0 y 1")
        if train_ratio + validation_ratio >= 1:
            raise ValueError("train + validación deben dejar espacio para test")

        corte_train = int(len(self) * train_ratio)
        corte_validacion = int(len(self) * (train_ratio + validation_ratio))
        tamanos = (corte_train, corte_validacion - corte_train, len(self) - corte_validacion)
        if min(tamanos) < 2:
            raise ValueError(
                f"hacen falta al menos 2 barras por tramo; tamaños obtenidos: {tamanos}"
            )

        return (
            self.slice(0, corte_train),
            self.slice(corte_train, corte_validacion),
            self.slice(corte_validacion),
        )


def build_dataset(
    candles: pd.DataFrame,
    params: FsrParams | None = None,
    cache_dir: Path | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Dataset:
    """Calcula (o recupera de caché) las características FSR de unas velas.

    Las primeras ``window - 1`` barras se descartan: no tienen ventana completa
    detrás y por tanto no pueden representarse sin inventar datos.
    """
    p = params or FsrParams()
    if "close" not in candles.columns:
        raise ValueError("el DataFrame de velas necesita una columna 'close'")

    prices = candles["close"].to_numpy(dtype=float)
    if prices.size < p.window + 1:
        raise ValueError(
            f"hacen falta más de {p.window} barras para construir el dataset, hay {prices.size}"
        )

    features = cached_features(
        prices, p, cache_dir=cache_dir, workers=workers, progress=progress
    )
    desfase = p.window - 1

    return Dataset(
        timestamps=candles.index[desfase:],
        prices=prices[desfase:],
        features=features.astype(np.float32),
    )
