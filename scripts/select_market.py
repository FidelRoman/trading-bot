"""Selecciona símbolo/timeframe en validación y abre test una sola vez.

Ejemplo:

    uv run python scripts/select_market.py \
        --symbols EUR/USD,XAU/USD,GBP/USD,USD/JPY \
        --timeframes h4,d1 --seeds 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.backtest import load_csv  # noqa: E402
from tradingbot.config import (  # noqa: E402
    PROJECT_ROOT,
    FsrParams,
    PpoParams,
    get_instrument_spec,
)
from tradingbot.rl.dataset import Dataset, build_dataset  # noqa: E402
from tradingbot.rl.env import EnvParams, units_for_notional  # noqa: E402
from tradingbot.rl.policy import FsrppoPolicy  # noqa: E402
from tradingbot.rl.registry import ModelRegistry  # noqa: E402
from tradingbot.rl.selection import rank_markets, winner_key  # noqa: E402
from tradingbot.rl.train import buy_and_hold, replay, train  # noqa: E402


def _csv_for(history_dir: Path, symbol: str, timeframe: str) -> Path:
    slug = symbol.replace("/", "").lower()
    matches = list(history_dir.glob(f"{slug}_{timeframe.lower()}_*.csv"))
    if not matches:
        raise FileNotFoundError(f"falta data para {symbol} {timeframe} en {history_dir}")
    return max(matches, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _median(values: list[float]) -> float:
    finite = [value for value in values if np.isfinite(value)]
    return float(np.median(finite)) if finite else float("nan")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def _market_env(spec, train_set: Dataset) -> EnvParams:
    # Mantiene la exposición máxima cerca del 2:1 original también cuando el
    # precio no está cerca de 1 USD (caso XAU/USD).
    base = EnvParams(instrument=spec)
    max_units = max(
        spec.min_lot,
        units_for_notional(2 * base.initial_equity, float(train_set.prices[0]), base),
    )
    return replace(base, max_units=max_units)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="EUR/USD,XAU/USD,GBP/USD,USD/JPY")
    parser.add_argument("--timeframes", default="h4,d1")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=PpoParams.iterations)
    parser.add_argument("--learning-rate", type=float, default=PpoParams.learning_rate)
    parser.add_argument("-j", "--workers", type=int, default=os.cpu_count())
    parser.add_argument("--history-dir", type=Path, default=PROJECT_ROOT / "data" / "history")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "selection")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.seeds < 1 or args.iterations < 1:
        raise SystemExit("--seeds y --iterations deben ser positivos")

    symbols = [get_instrument_spec(value).symbol for value in args.symbols.split(",") if value.strip()]
    timeframes = [value.strip().lower() for value in args.timeframes.split(",") if value.strip()]
    if not symbols or not timeframes:
        raise SystemExit("hay que indicar al menos un símbolo y un timeframe")

    fsr = FsrParams()
    registry = ModelRegistry()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidates: list[dict[str, Any]] = []
    held_out: dict[tuple[str, str], Dataset] = {}
    sources: dict[tuple[str, str], tuple[Path, Any]] = {}

    # Todos los mercados se comparan sobre la misma ventana cronológica. Elegir
    # "el CSV más nuevo" por mercado sin recortar la intersección comparaba años
    # y regímenes distintos con una métrica aparentemente homogénea.
    for symbol in symbols:
        for timeframe in timeframes:
            csv_path = _csv_for(args.history_dir, symbol, timeframe)
            candles = load_csv(csv_path, timeframe=timeframe)
            sources[(symbol, timeframe)] = (csv_path, candles)
    common_start = max(candles.index[0] for _, candles in sources.values())
    common_end = min(candles.index[-1] for _, candles in sources.values())
    if common_start >= common_end:
        raise SystemExit("los históricos no comparten una ventana temporal")

    for symbol in symbols:
        spec = get_instrument_spec(symbol)
        for timeframe in timeframes:
            csv_path, full_candles = sources[(symbol, timeframe)]
            print(f"\n{symbol} {timeframe.upper()} · {csv_path.name}")
            candles = full_candles.loc[common_start:common_end]
            dataset = build_dataset(candles, fsr, workers=args.workers)
            train_set, validation_set, test_set = dataset.split_three_way()
            held_out[(symbol, timeframe)] = test_set

            env = _market_env(spec, train_set)
            validation_benchmark = buy_and_hold(validation_set, env, timeframe)
            seeds: list[dict[str, Any]] = []
            slug = symbol.replace("/", "").lower()

            for seed in range(args.seeds):
                ppo = replace(
                    PpoParams(),
                    iterations=args.iterations,
                    learning_rate=args.learning_rate,
                    seed=seed,
                )
                run_id = f"selection-{stamp}-{slug}-{timeframe}-s{seed}"
                outcome = train(
                    train_set,
                    validation_set,
                    fsr_params=fsr,
                    ppo_params=ppo,
                    env_params=env,
                    timeframe=timeframe,
                    instrument=symbol,
                    registry=registry,
                    run_id=run_id,
                )
                metrics = outcome.test_replay.metrics.as_dict()
                seeds.append({"seed": seed, "run_id": run_id, "metrics": metrics})
                print(
                    f"  semilla {seed:2d}: Sharpe {metrics['sharpe']:8.3f} · "
                    f"CRR {100 * metrics['crr']:8.2f}%"
                )

            median_sharpe = _median([row["metrics"]["sharpe"] for row in seeds])
            median_crr = _median([row["metrics"]["crr"] for row in seeds])
            candidates.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "csv": csv_path.name,
                "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "ranges": {
                    "train": [str(train_set.timestamps[0]), str(train_set.timestamps[-1])],
                    "validation": [str(validation_set.timestamps[0]), str(validation_set.timestamps[-1])],
                    # Solo se registran límites; todavía no se han calculado métricas de test.
                    "test": [str(test_set.timestamps[0]), str(test_set.timestamps[-1])],
                },
                "validation": {
                    "median_sharpe": median_sharpe,
                    "median_crr": median_crr,
                    "benchmark_crr": validation_benchmark.metrics.crr,
                    "seeds": seeds,
                },
            })

    ranking = rank_markets(candidates)
    try:
        symbol, timeframe = winner_key(ranking)
    except ValueError as exc:
        document = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "protocol": {"train": 0.60, "validation": 0.20, "test": 0.20},
            "common_range": [str(common_start), str(common_end)],
            "settings": {
                "symbols": symbols,
                "timeframes": timeframes,
                "seeds": args.seeds,
            },
            "ranking": ranking,
            "winner": None,
            "test": {"status": "not_opened", "reason": str(exc)},
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / f"{stamp}.json"
        output.write_text(json.dumps(_json_safe(document), indent=2, ensure_ascii=False) + "\n")
        print(f"\nSIN GANADOR: {exc}")
        print(f"Auditoría: {output}")
        return 2
    winning = next(row for row in ranking if row["winner"])
    test_set = held_out[(symbol, timeframe)]

    # Esta es la primera y única evaluación del tramo reservado: solo se cargan
    # los modelos de la combinación ya elegida por validación.
    test_seeds: list[dict[str, Any]] = []
    for seed_row in winning["validation"]["seeds"]:
        policy = FsrppoPolicy.from_record(registry, seed_row["run_id"])
        result = replay(policy.agent, test_set, policy.env_params, timeframe)
        test_seeds.append({
            "seed": seed_row["seed"],
            "run_id": seed_row["run_id"],
            "metrics": result.metrics.as_dict(),
            "trades": result.trades,
        })

    first_policy = FsrppoPolicy.from_record(registry, test_seeds[0]["run_id"])
    benchmark = buy_and_hold(test_set, first_policy.env_params, timeframe)
    passed = sum(
        1
        for row in test_seeds
        if np.isfinite(row["metrics"]["sharpe"])
        and row["metrics"]["sharpe"] > 0
        and row["metrics"]["crr"] > benchmark.metrics.crr
    )
    required = math.ceil(0.7 * args.seeds)

    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {"train": 0.60, "validation": 0.20, "test": 0.20},
        "common_range": [str(common_start), str(common_end)],
        "settings": {
            "symbols": symbols,
            "timeframes": timeframes,
            "seeds": args.seeds,
            "ppo": asdict(replace(PpoParams(), iterations=args.iterations,
                                  learning_rate=args.learning_rate)),
            "fsr": asdict(fsr),
        },
        "ranking": ranking,
        "winner": {"symbol": symbol, "timeframe": timeframe},
        "test": {
            "benchmark_metrics": benchmark.metrics.as_dict(),
            "seeds": test_seeds,
            "passed": passed,
            "required": required,
            "total": args.seeds,
            "accepted": passed >= required,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{stamp}.json"
    output.write_text(json.dumps(_json_safe(document), indent=2, ensure_ascii=False) + "\n")

    print("\nRANKING DE VALIDACIÓN")
    for row in ranking:
        marker = "★" if row["winner"] else " "
        status = "apta" if row["eligible"] else "no supera Sharpe > 0 y CRR > B&H"
        print(
            f"{marker} {row['rank']:2d}. {row['symbol']:7s} {row['timeframe'].upper():3s} "
            f"Sharpe {row['validation']['median_sharpe']:8.3f} · "
            f"CRR {100 * row['validation']['median_crr']:8.2f}% · {status}"
        )
    print(f"\nTEST {symbol} {timeframe.upper()}: {passed}/{args.seeds} semillas ({required} requeridas)")
    print("VEREDICTO:", "APROBADO" if passed >= required else "NO APROBADO; no activar auto-trading")
    print(f"Auditoría: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
