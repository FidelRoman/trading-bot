"""Precálculo paralelo y caché en disco de las características FSR.

CEESMDAN cuesta ~0,9 s por ventana: recalcularlo en cada paso de PPO, que
recorre el histórico cientos de veces, sería inviable. Pero ``fsr_window`` solo
depende de la ventana de ``M`` cierres que termina en la barra evaluada, así que
la matriz de características se calcula una vez, se guarda en disco y el
entrenamiento la lee de memoria.

**La caché se indexa por ventana, no por serie.** Cada fila se guarda bajo una
huella de sus propios ``M`` precios, de modo que descargar velas nuevas solo
obliga a calcular las ventanas nuevas: las 12.610 anteriores se reutilizan. Con
una clave por serie completa —como estaba antes— añadir una sola barra
invalidaba el histórico entero y convertía un coste único en recurrente.

Convención de alineación: ``features[i]`` corresponde a la barra
``prices[i + window - 1]``, la última de su propia ventana. Nunca hay
información posterior a esa barra dentro de la fila.
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from ..config import PROJECT_ROOT, FsrParams
from .represent import fsr_features

__all__ = [
    "CACHE_DIR",
    "DEFAULT_WORKERS",
    "cache_path",
    "compute_features",
    "cached_features",
    "window_keys",
]

CACHE_DIR = PROJECT_ROOT / "data" / "fsr_cache"

# Por defecto se usa la mitad de los núcleos: saturar la máquina la calienta y
# la deja inutilizable mientras dura. Con -j se puede pedir el total.
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) // 2)

# Cada cuántas ventanas se vuelca el progreso a disco. Sin esto, una
# interrupción a mitad tiraba horas de cálculo.
CHECKPOINT_EVERY = 512

_PRICES: np.ndarray | None = None
_PARAMS: FsrParams | None = None


def window_keys(prices: np.ndarray, window: int) -> np.ndarray:
    """Huella de 64 bits de cada ventana deslizante de ``prices``.

    Con ~10⁴ ventanas, la probabilidad de colisión en 64 bits es del orden de
    10⁻¹², muy por debajo de cualquier otra fuente de error del sistema.
    """
    prices = np.ascontiguousarray(prices, dtype=float)
    total = prices.size - window + 1
    if total <= 0:
        return np.empty(0, dtype=np.uint64)

    ventanas = np.lib.stride_tricks.sliding_window_view(prices, window)
    return np.array(
        [
            int.from_bytes(hashlib.blake2b(v.tobytes(), digest_size=8).digest(), "big")
            for v in ventanas
        ],
        dtype=np.uint64,
    )


def cache_path(params: FsrParams, cache_dir: Path | None = None) -> Path:
    """Ruta del almacén para estos parámetros.

    Depende solo de los hiperparámetros: los precios ya no forman parte de la
    clave, porque cada ventana se indexa por separado dentro del fichero.
    """
    directory = Path(cache_dir) if cache_dir else CACHE_DIR
    return directory / f"fsr_{params.cache_key()}.npz"


def _load_store(path: Path) -> dict[int, np.ndarray]:
    if not path.exists():
        return {}
    try:
        with np.load(path) as data:
            keys, values = data["keys"], data["features"]
    except (OSError, KeyError, ValueError):
        # Un fichero truncado o de un formato viejo no debe impedir arrancar:
        # se recalcula lo que falte.
        return {}
    return {int(k): v for k, v in zip(keys, values)}


def _save_store(path: Path, store: dict[int, np.ndarray]) -> None:
    if not store:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = np.fromiter(store.keys(), dtype=np.uint64, count=len(store))
    values = np.stack([store[int(k)] for k in keys])
    tmp = path.with_suffix(".npz.tmp")
    # Hay que pasar un descriptor abierto: con una ruta, numpy le añade ".npz"
    # al nombre y el temporal acabaría en otro sitio.
    with open(tmp, "wb") as handle:
        np.savez_compressed(handle, keys=keys, features=values)
    tmp.replace(path)


def _import_legacy(
    directory: Path, params: FsrParams, keys: np.ndarray, total: int
) -> dict[int, np.ndarray]:
    """Rescata una caché del formato antiguo (una matriz por serie completa).

    El formato anterior guardaba ``fsr_<serie>_<params>.npz`` con las filas en
    orden. Si hay uno cuyo número de filas cuadra con esta serie, se reindexa
    por ventana en vez de tirar horas de cálculo a la basura.
    """
    for legacy in sorted(directory.glob(f"fsr_*_{params.cache_key()}.npz")):
        try:
            with np.load(legacy) as data:
                if "features" not in data or "keys" in data:
                    continue
                features = data["features"]
        except (OSError, KeyError, ValueError):
            continue
        if features.shape[0] == total:
            return {int(k): f for k, f in zip(keys, features)}
    return {}


def _init_worker(prices: np.ndarray, params: FsrParams) -> None:
    global _PRICES, _PARAMS
    _PRICES, _PARAMS = prices, params


def _worker(indices: np.ndarray) -> np.ndarray:
    assert _PRICES is not None and _PARAMS is not None
    window = _PARAMS.window
    return np.array([fsr_features(_PRICES[i : i + window], _PARAMS) for i in indices])


def _chunks(items: np.ndarray, size: int) -> Iterable[np.ndarray]:
    return (items[i : i + size] for i in range(0, items.size, size))


def compute_features(
    prices: np.ndarray,
    params: FsrParams | None = None,
    workers: int | None = None,
    chunk_size: int = 64,
    progress: Callable[[int, int], None] | None = None,
) -> np.ndarray:
    """Matriz ``(N - window + 1, window)`` de características FSR, sin caché."""
    p = params or FsrParams()
    prices = np.asarray(prices, dtype=float)
    total = prices.size - p.window + 1
    if total <= 0:
        raise ValueError(
            f"se necesitan al menos {p.window} precios para calcular FSR, hay {prices.size}"
        )
    filas = _compute_missing(prices, p, np.arange(total), workers, chunk_size, progress)
    return np.stack([filas[i] for i in range(total)])


def _compute_missing(
    prices: np.ndarray,
    params: FsrParams,
    indices: np.ndarray,
    workers: int | None,
    chunk_size: int,
    progress: Callable[[int, int], None] | None,
    on_chunk: Callable[[dict[int, np.ndarray]], None] | None = None,
) -> dict[int, np.ndarray]:
    """Calcula las filas pedidas y las devuelve indexadas por posición."""
    resultado: dict[int, np.ndarray] = {}
    if indices.size == 0:
        return resultado

    bloques = list(_chunks(indices, chunk_size))
    total = int(indices.size)
    hechas = 0
    n_workers = DEFAULT_WORKERS if workers is None else workers

    def registrar(bloque: np.ndarray, filas: np.ndarray) -> None:
        nonlocal hechas
        nuevas = {int(i): f for i, f in zip(bloque, filas)}
        resultado.update(nuevas)
        hechas += bloque.size
        if on_chunk:
            on_chunk(nuevas)
        if progress:
            progress(hechas, total)

    if n_workers == 1:
        _init_worker(prices, params)
        for bloque in bloques:
            registrar(bloque, _worker(bloque))
    else:
        with ProcessPoolExecutor(
            max_workers=n_workers, initializer=_init_worker, initargs=(prices, params)
        ) as pool:
            for bloque, filas in zip(bloques, pool.map(_worker, bloques)):
                registrar(bloque, filas)

    return resultado


def cached_features(
    prices: np.ndarray,
    params: FsrParams | None = None,
    cache_dir: Path | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    refresh: bool = False,
) -> np.ndarray:
    """Características FSR reutilizando lo ya calculado para estas ventanas.

    Solo se calculan las ventanas que no estén ya en el almacén, y el progreso
    se vuelca a disco cada ``CHECKPOINT_EVERY`` ventanas.
    """
    p = params or FsrParams()
    prices = np.asarray(prices, dtype=float)
    total = prices.size - p.window + 1
    if total <= 0:
        raise ValueError(
            f"se necesitan al menos {p.window} precios para calcular FSR, hay {prices.size}"
        )

    path = cache_path(p, cache_dir)
    store = {} if refresh else _load_store(path)
    keys = window_keys(prices, p.window)

    if not refresh and not store:
        store = _import_legacy(path.parent, p, keys, total)
        if store:
            _save_store(path, store)

    faltan = np.array([i for i, k in enumerate(keys) if int(k) not in store], dtype=int)
    if progress and faltan.size == 0:
        progress(total, total)

    if faltan.size:
        desde_ultimo = 0

        def volcar(nuevas: dict[int, np.ndarray]) -> None:
            nonlocal desde_ultimo
            for i, fila in nuevas.items():
                store[int(keys[i])] = fila
            desde_ultimo += len(nuevas)
            if desde_ultimo >= CHECKPOINT_EVERY:
                _save_store(path, store)
                desde_ultimo = 0

        _compute_missing(prices, p, faltan, workers, 64, progress, on_chunk=volcar)
        _save_store(path, store)

    return np.stack([store[int(k)] for k in keys])
