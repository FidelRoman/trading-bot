"""Precalcula y cachea la matriz de características FSR de una serie de precios.

CEESMDAN cuesta ~1,7 s por ventana con los parámetros del paper. Este script lo
paga una sola vez: el resultado queda en ``data/fsr_cache/`` y el entrenamiento
lo lee de memoria.

    uv run python scripts/precompute_fsr.py                       # H1 por defecto
    uv run python scripts/precompute_fsr.py --csv otro.csv -j 4
    uv run python scripts/precompute_fsr.py --patience 8          # ~4x más rápido
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.config import PROJECT_ROOT, FsrParams  # noqa: E402
from tradingbot.fsr.cache import DEFAULT_WORKERS, cache_path, cached_features  # noqa: E402

def default_csv() -> Path:
    history_dir = PROJECT_ROOT / "data" / "history"
    matches = sorted(history_dir.glob("eurusd_h1_*.csv"))
    if matches:
        return matches[-1]
    return history_dir / "eurusd_h1_20240811_20260811.csv"


def _format_eta(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=default_csv(), help="CSV con columna 'close'")
    parser.add_argument("-j", "--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"procesos en paralelo (por defecto {DEFAULT_WORKERS}, la mitad de los núcleos)")
    parser.add_argument("--window", type=int, default=FsrParams.window)
    parser.add_argument("--ensemble", type=int, default=FsrParams.ensemble_size)
    parser.add_argument(
        "--patience",
        type=int,
        default=None,
        help="parada temprana del tamizado; por defecto las D=100 pasadas del paper",
    )
    parser.add_argument("--refresh", action="store_true", help="recalcular aunque haya caché")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"No existe {args.csv}", file=sys.stderr)
        return 1

    frame = pd.read_csv(args.csv)
    prices = frame["close"].to_numpy(dtype=float)
    params = FsrParams(
        window=args.window, ensemble_size=args.ensemble, patience=args.patience
    )

    destino = cache_path(params)
    total = len(prices) - params.window + 1
    print(f"Serie    : {args.csv.name} ({len(prices)} barras)")
    print(f"Ventanas : {total}   workers: {args.workers}")
    print(f"Destino  : {destino}")

    # No se comprueba si el fichero existe: la caché es por ventana, así que
    # `cached_features` calcula solo lo que falte y reutiliza el resto.
    started = time.perf_counter()

    def progress(done: int, total: int) -> None:
        elapsed = time.perf_counter() - started
        rate = done / elapsed if elapsed > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        pct = 100.0 * done / total
        print(
            f"\r  {done}/{total} ({pct:5.1f}%)  {rate:6.1f} ventanas/s  ETA {_format_eta(eta)}   ",
            end="",
            flush=True,
        )

    features = cached_features(
        prices, params, workers=args.workers, progress=progress, refresh=args.refresh
    )
    print(f"\nListo en {_format_eta(time.perf_counter() - started)} — matriz {features.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
