"""Barre hiperparámetros de FSRPPO para un símbolo y elige uno por validación.

Complementa a select_market.py (que barre símbolo/timeframe) y a
train_fsrppo.py (que entrena un único punto): aquí se prueban varias
combinaciones de learning rate y coeficiente de entropía sobre el mismo
símbolo, con el mismo protocolo de tres tramos —el tramo de test se abre una
sola vez, para la combinación ganadora en validación—.

Etapa 1 (selección): tres tramos vía Dataset.split_three_way() (60/20/20).
Cada combinación (lr, entropía) se entrena sobre train y se evalúa sobre
validación, con pocas semillas y pocas iteraciones. Se rankea por Sharpe y
CRR medianos en validación frente a comprar-y-mantener, igual que
select_market.py rankea mercados.

Etapa 2 (aceptación): la combinación ganadora se reentrena con más semillas
y más iteraciones sobre train+validación combinados, y se evalúa una sola
vez sobre el tramo de test que quedó cerrado. El veredicto es el mismo
criterio de PLAN.md que usa train_fsrppo.py: Sharpe > 0 y CRR > B&H en al
menos 7 de cada 10 semillas.

    uv run python scripts/sweep_fsrppo.py --symbol XAU/USD --timeframe h4 \
        --learning-rates 1e-4,3e-4,1e-3,3e-3 --entropy-coefs 0.01,0.05
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.backtest import load_csv  # noqa: E402
from tradingbot.config import PROJECT_ROOT, FsrParams, PpoParams, get_instrument_spec  # noqa: E402
from tradingbot.rl.dataset import build_dataset  # noqa: E402
from tradingbot.rl.env import EnvParams, units_for_notional  # noqa: E402
from tradingbot.rl.registry import ModelRegistry  # noqa: E402
from tradingbot.rl.train import buy_and_hold, train  # noqa: E402


def _csv_for(history_dir: Path, symbol: str, timeframe: str) -> Path:
    slug = symbol.replace("/", "").lower()
    matches = list(history_dir.glob(f"{slug}_{timeframe.lower()}_*.csv"))
    if not matches:
        raise FileNotFoundError(f"falta data para {symbol} {timeframe} en {history_dir}")
    return max(matches, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _median(values: list[float]) -> float:
    finite = [v for v in values if np.isfinite(v)]
    return float(np.median(finite)) if finite else float("nan")


def _market_env(spec, first_price: float) -> EnvParams:
    base = EnvParams(instrument=spec)
    max_units = max(spec.min_lot, units_for_notional(2 * base.initial_equity, first_price, base))
    return replace(base, max_units=max_units)


def _score(row: dict[str, Any]) -> tuple[int, float, float]:
    v = row["validation"]
    sharpe, crr, bench = v["median_sharpe"], v["median_crr"], v["benchmark_crr"]
    eligible = np.isfinite(sharpe) and sharpe > 0 and np.isfinite(crr) and crr > bench
    return (int(eligible), sharpe if np.isfinite(sharpe) else -np.inf, crr if np.isfinite(crr) else -np.inf)


def fila(nombre: str, metricas, operaciones: int | str = "—") -> str:
    def pct(v):
        return f"{100 * v:8.2f}%" if v is not None and np.isfinite(v) else "       —"

    def num(v):
        return f"{v:8.3f}" if v is not None and np.isfinite(v) else "       —"

    return (
        f"{nombre:>18} {pct(metricas.crr)} {pct(metricas.arr)} {pct(metricas.max_drawdown)} "
        f"{num(metricas.sharpe)} {num(metricas.calmar)} {num(metricas.sortino)} {operaciones:>6}"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default="XAU/USD")
    p.add_argument("--timeframe", default="h4")
    p.add_argument("--history-dir", type=Path, default=PROJECT_ROOT / "data" / "history")
    p.add_argument("--learning-rates", default="1e-4,3e-4,1e-3,3e-3")
    p.add_argument("--entropy-coefs", default="0.01,0.05")
    p.add_argument("--seeds", type=int, default=3, help="semillas en la etapa de selección (validación)")
    p.add_argument("--iterations", type=int, default=150, help="iteraciones en la etapa de selección")
    p.add_argument("--final-seeds", type=int, default=10, help="semillas en la etapa de aceptación (test)")
    p.add_argument("--final-iterations", type=int, default=PpoParams.iterations)
    p.add_argument("-j", "--workers", type=int, default=os.cpu_count())
    p.add_argument("--activate-best", action="store_true")
    p.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "sweeps")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    spec = get_instrument_spec(args.symbol)
    lrs = [float(x) for x in args.learning_rates.split(",") if x.strip()]
    ents = [float(x) for x in args.entropy_coefs.split(",") if x.strip()]
    if not lrs or not ents:
        raise SystemExit("hacen falta learning rates y coeficientes de entropía")

    csv_path = _csv_for(args.history_dir, spec.symbol, args.timeframe)
    candles = load_csv(csv_path, timeframe=args.timeframe)
    fsr = FsrParams()
    print(f"{spec.symbol} {args.timeframe.upper()} · {csv_path.name}")
    print(f"Velas: {len(candles)} ({candles.index[0]:%Y-%m-%d} → {candles.index[-1]:%Y-%m-%d})")

    dataset = build_dataset(candles, fsr, workers=args.workers)
    train_set, validation_set, test_set = dataset.split_three_way()
    print(f"Train      : {len(train_set):6d} barras  {train_set.timestamps[0]:%Y-%m-%d} → {train_set.timestamps[-1]:%Y-%m-%d}")
    print(f"Validación : {len(validation_set):6d} barras  {validation_set.timestamps[0]:%Y-%m-%d} → {validation_set.timestamps[-1]:%Y-%m-%d}")
    print(f"Test       : {len(test_set):6d} barras  {test_set.timestamps[0]:%Y-%m-%d} → {test_set.timestamps[-1]:%Y-%m-%d}  [cerrado]")

    env = _market_env(spec, float(train_set.prices[0]))
    print(f"Exposición máxima: {env.max_units} {spec.symbol.split('/')[0]} "
          f"(~{env.max_units * float(train_set.prices[0]):,.0f} USD de nocional)\n")

    validation_benchmark = buy_and_hold(validation_set, env, args.timeframe)
    registry = ModelRegistry()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = spec.symbol.replace("/", "").lower()

    print(f"=== Etapa 1: selección por validación ({len(lrs)}x{len(ents)} combinaciones, "
          f"{args.seeds} semillas, {args.iterations} iteraciones) ===")
    print(fila("B&H (validación)", validation_benchmark.metrics, validation_benchmark.trades))

    candidates: list[dict[str, Any]] = []
    for lr in lrs:
        for ent in ents:
            etiqueta = f"lr={lr:g} ent={ent:g}"
            seeds_rows = []
            for seed in range(args.seeds):
                run_id = f"sweep-{stamp}-{slug}-lr{lr:g}-ent{ent:g}-s{seed}"
                empezado = time.perf_counter()
                ppo = PpoParams(iterations=args.iterations, seed=seed, learning_rate=lr, entropy_coef=ent)
                outcome = train(
                    train_set, validation_set, fsr_params=fsr, ppo_params=ppo, env_params=env,
                    timeframe=args.timeframe, instrument=spec.symbol, registry=registry, run_id=run_id,
                )
                m = outcome.test_replay.metrics.as_dict()
                seeds_rows.append({"seed": seed, "run_id": run_id, "metrics": m})
                print(
                    fila(f"{etiqueta} s{seed}", outcome.test_replay.metrics, outcome.test_replay.trades)
                    + f"   [{time.perf_counter() - empezado:5.0f}s]"
                )
            median_sharpe = _median([r["metrics"]["sharpe"] for r in seeds_rows])
            median_crr = _median([r["metrics"]["crr"] for r in seeds_rows])
            candidates.append({
                "learning_rate": lr, "entropy_coef": ent, "label": etiqueta,
                "validation": {
                    "median_sharpe": median_sharpe, "median_crr": median_crr,
                    "benchmark_crr": validation_benchmark.metrics.crr, "seeds": seeds_rows,
                },
            })

    candidates.sort(key=_score, reverse=True)
    for i, row in enumerate(candidates, start=1):
        row["rank"] = i
        row["eligible"] = bool(_score(row)[0])
    print("\nRanking de validación:")
    for row in candidates:
        v = row["validation"]
        marca = "✓" if row["eligible"] else " "
        print(f"  {marca} #{row['rank']} {row['label']:<18} Sharpe med. {v['median_sharpe']:7.3f}  "
              f"CRR med. {100*v['median_crr']:7.2f}%  (B&H {100*v['benchmark_crr']:7.2f}%)")

    winner = candidates[0]
    if not winner["eligible"]:
        print(f"\nNINGUNA combinación supera Sharpe > 0 y CRR > B&H en validación. "
              f"Se continúa con la mejor de todas formas ({winner['label']}) para dejar constancia en test, "
              f"pero no se espera que apruebe.")
    else:
        print(f"\nGanadora en validación: {winner['label']}")

    # -- Etapa 2: aceptación, con test cerrado hasta ahora ------------------
    trainval_set, _ = dataset.split(train_end=validation_set.timestamps[-1])
    print(f"\n=== Etapa 2: aceptación sobre test ({args.final_seeds} semillas, "
          f"{args.final_iterations} iteraciones, lr={winner['learning_rate']:g} ent={winner['entropy_coef']:g}) ===")
    print(f"Train+val  : {len(trainval_set):6d} barras hasta {trainval_set.timestamps[-1]:%Y-%m-%d}")
    print(fila("B&H (test)", buy_and_hold(test_set, env, args.timeframe).metrics,
                buy_and_hold(test_set, env, args.timeframe).trades))

    final_results = []
    for seed in range(args.final_seeds):
        empezado = time.perf_counter()
        run_id = f"fsrppo-sweep-{stamp}-{slug}-final-s{seed}"
        ppo = PpoParams(iterations=args.final_iterations, seed=seed,
                        learning_rate=winner["learning_rate"], entropy_coef=winner["entropy_coef"])
        outcome = train(
            trainval_set, test_set, fsr_params=fsr, ppo_params=ppo, env_params=env,
            timeframe=args.timeframe, instrument=spec.symbol, registry=registry, run_id=run_id,
        )
        final_results.append(outcome)
        print(fila(str(seed), outcome.test_replay.metrics, outcome.test_replay.trades)
              + f"   [{time.perf_counter() - empezado:5.0f}s  {outcome.record.run_id}]")

    referencia = buy_and_hold(test_set, env, args.timeframe)
    sharpes = [r.test_replay.metrics.sharpe for r in final_results]
    crrs = [r.test_replay.metrics.crr for r in final_results]
    baten = sum(1 for s, c in zip(sharpes, crrs) if np.isfinite(s) and s > 0 and c > referencia.metrics.crr)
    finite = [s for s in sharpes if np.isfinite(s)]
    print(f"\nCRR mediano   : {100*float(np.median(crrs)):.2f}%   (B&H: {100*referencia.metrics.crr:.2f}%)")
    print(f"Sharpe mediano: {float(np.median(finite)):.3f}" if finite else "Sharpe mediano: —")
    print(f"Semillas con Sharpe > 0 y CRR > B&H: {baten}/{len(final_results)}")

    umbral = int(math.ceil(0.7 * len(final_results)))
    passed = baten >= umbral
    if passed:
        print("VEREDICTO: supera el criterio de aceptación de PLAN.md.")
    else:
        print(f"VEREDICTO: NO supera el criterio ({umbral} de {len(final_results)} necesarias).")

    best = max(final_results, key=lambda r: r.test_replay.metrics.sharpe
               if np.isfinite(r.test_replay.metrics.sharpe) else -np.inf)
    print(f"Mejor semilla por Sharpe: {best.record.run_id} "
          f"(Sharpe {best.test_replay.metrics.sharpe:.3f}, CRR {100*best.test_replay.metrics.crr:.2f}%)")

    if args.activate_best:
        registry.activate(best.record.run_id)
        print(f"Modelo activo para {spec.symbol}: {best.record.run_id}")

    def _safe(v):
        if isinstance(v, dict):
            return {k: _safe(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_safe(x) for x in v]
        if isinstance(v, (float, np.floating)):
            return float(v) if np.isfinite(v) else None
        if isinstance(v, np.integer):
            return int(v)
        return v

    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": spec.symbol, "timeframe": args.timeframe, "csv": csv_path.name,
        "selection": candidates,
        "winner": {"learning_rate": winner["learning_rate"], "entropy_coef": winner["entropy_coef"]},
        "acceptance": {
            "seeds": [{"seed": i, "run_id": r.record.run_id, "metrics": r.test_replay.metrics.as_dict()}
                      for i, r in enumerate(final_results)],
            "benchmark_crr": referencia.metrics.crr,
            "passed": passed, "best_run_id": best.record.run_id,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{stamp}-{slug}.json"
    out.write_text(json.dumps(_safe(document), indent=2, ensure_ascii=False) + "\n")
    print(f"\nAuditoría: {out}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
