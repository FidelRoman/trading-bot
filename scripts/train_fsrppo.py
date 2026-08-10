"""Entrena FSRPPO sobre EUR/USD y lo evalúa fuera de muestra.

Repite el entrenamiento con varias semillas —como hace el paper, que promedia 10
repeticiones— porque un único run puede salir bien por azar. El veredicto final
aplica el criterio de aceptación de PLAN.md: Sharpe > 0 y CRR mejor que
comprar-y-mantener en el tramo de test, en al menos 7 de cada 10 semillas.

    uv run python scripts/train_fsrppo.py --train-end 2026-01-01 --seeds 10
    uv run python scripts/train_fsrppo.py --seeds 1 --iterations 20    # prueba rápida
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.backtest import load_csv  # noqa: E402
from tradingbot.config import PROJECT_ROOT, FsrParams, PpoParams, get_instrument_spec  # noqa: E402
from tradingbot.rl.dataset import build_dataset  # noqa: E402
from tradingbot.rl.env import EnvParams  # noqa: E402
from tradingbot.rl.registry import ModelRegistry  # noqa: E402
from tradingbot.rl.train import buy_and_hold, train  # noqa: E402

DEFAULT_CSV = PROJECT_ROOT / "data" / "history" / "eurusd_h1_20240708_20260708.csv"
CABECERA = f"{'semilla':>8} {'CRR':>9} {'ARR':>9} {'MD':>8} {'Sharpe':>8} {'Calmar':>8} {'Sortino':>8} {'ops':>6}"


def fila(nombre: str, metricas, operaciones: int | str = "—") -> str:
    def pct(v):
        return f"{100 * v:8.2f}%" if v is not None and np.isfinite(v) else "       —"

    def num(v):
        return f"{v:8.3f}" if v is not None and np.isfinite(v) else "       —"

    return (
        f"{nombre:>8} {pct(metricas.crr)} {pct(metricas.arr)} {pct(metricas.max_drawdown)} "
        f"{num(metricas.sharpe)} {num(metricas.calmar)} {num(metricas.sortino)} {operaciones:>6}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--timeframe", default="h1")
    parser.add_argument("--instrument", default="EUR/USD")
    parser.add_argument("--train-end", default=None,
                        help="fecha de corte train/test (por defecto, el 75 %% del histórico)")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=PpoParams.iterations)
    parser.add_argument("--learning-rate", type=float, default=PpoParams.learning_rate,
                        help="el 1e-5 del paper no llega a operar en EUR/USD H1; ver README")
    parser.add_argument("-j", "--workers", type=int, default=os.cpu_count())
    parser.add_argument("--activate-best", action="store_true",
                        help="promover a modelo activo el mejor run por Sharpe de test")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"No existe {args.csv}", file=sys.stderr)
        return 1

    candles = load_csv(args.csv, timeframe=args.timeframe)
    fsr = FsrParams()
    print(f"Velas    : {len(candles)} ({candles.index[0]:%Y-%m-%d} → {candles.index[-1]:%Y-%m-%d})")
    print("FSR      : leyendo caché (si falta, se calcula ahora y tarda)…")

    dataset = build_dataset(candles, fsr, workers=args.workers)

    corte = args.train_end or dataset.timestamps[int(len(dataset) * 0.75)]
    entrena, evalua = dataset.split(corte)
    print(f"Train    : {len(entrena):6d} barras  {entrena.timestamps[0]:%Y-%m-%d} → {entrena.timestamps[-1]:%Y-%m-%d}")
    print(f"Test     : {len(evalua):6d} barras  {evalua.timestamps[0]:%Y-%m-%d} → {evalua.timestamps[-1]:%Y-%m-%d}")

    spec = get_instrument_spec(args.instrument)
    env_cfg = EnvParams(instrument=spec)
    referencia = buy_and_hold(evalua, env_cfg, args.timeframe)
    registro = ModelRegistry()

    print(f"\nResultados sobre el tramo de TEST ({args.seeds} semillas, {args.iterations} iteraciones)")
    print(CABECERA)
    print(fila("B&H", referencia.metrics, referencia.trades))

    resultados = []
    for semilla in range(args.seeds):
        empezado = time.perf_counter()
        ppo = PpoParams(iterations=args.iterations, seed=semilla,
                        learning_rate=args.learning_rate)
        salida = train(
            entrena, evalua,
            fsr_params=fsr, ppo_params=ppo, env_params=env_cfg,
            timeframe=args.timeframe, instrument=spec.symbol, registry=registro,
        )
        resultados.append(salida)
        print(
            fila(str(semilla), salida.test_replay.metrics, salida.test_replay.trades)
            + f"   [{time.perf_counter() - empezado:5.0f}s  {salida.record.run_id}]"
        )

    # -- veredicto ---------------------------------------------------------
    sharpes = [r.test_replay.metrics.sharpe for r in resultados]
    crrs = [r.test_replay.metrics.crr for r in resultados]
    baten = sum(
        1 for s, c in zip(sharpes, crrs)
        if np.isfinite(s) and s > 0 and c > referencia.metrics.crr
    )

    print(f"\nCRR mediano   : {100 * float(np.median(crrs)):.2f}%   (B&H: {100 * referencia.metrics.crr:.2f}%)")
    print(f"Sharpe mediano: {float(np.nanmedian(sharpes)):.3f}")
    print(f"Semillas con Sharpe > 0 y CRR > B&H: {baten}/{len(resultados)}")

    umbral = int(np.ceil(0.7 * len(resultados)))
    if baten >= umbral:
        print("VEREDICTO: supera el criterio de aceptación de PLAN.md.")
    else:
        print(
            f"VEREDICTO: NO supera el criterio ({umbral} de {len(resultados)} necesarias). "
            "La estrategia se queda en backtest; no activar auto-trading."
        )

    if args.activate_best and resultados:
        mejor = max(
            resultados,
            key=lambda r: r.test_replay.metrics.sharpe
            if np.isfinite(r.test_replay.metrics.sharpe) else -np.inf,
        )
        registro.activate(mejor.record.run_id)
        print(f"Modelo activo: {mejor.record.run_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
