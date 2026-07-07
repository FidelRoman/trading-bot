"""Búsqueda de parámetros con validación out-of-sample.

Divide el histórico en TRAIN (primeros 2/3) y TEST (último 1/3): optimiza en
TRAIN y valida los mejores en TEST. Solo un parámetro que funcione en AMBOS
tramos merece considerarse — lo demás es sobreajuste.

Uso: uv run python scripts/optimize.py data/history/eurusd_m15_*.csv
"""
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradingbot.backtest import load_csv, run_backtest
from tradingbot.config import RiskParams, StrategyParams

SPREAD = 1.3          # pips, algo peor que el típico de FXCM demo
MIN_TRADES_TRAIN = 60 # menos trades = sin significancia

GRID = {
    "bb_std": [2.0, 2.5, 3.0],
    "sl_atr_mult": [1.5, 2.0, 3.0],
    "min_band_width_pips": [0.0, 8.0, 12.0],
}


def run(df, params: StrategyParams) -> dict:
    r = run_backtest(df, params, RiskParams(), initial_equity=10_000, spread_pips=SPREAD)
    return r.summary()


def main() -> None:
    csv = sys.argv[1] if len(sys.argv) > 1 else None
    if csv is None:
        candidates = sorted((ROOT / "data" / "history").glob("eurusd_m15_*.csv"))
        if not candidates:
            raise SystemExit("Sin histórico: corre antes run_backtest.py o pasa un CSV")
        csv = candidates[-1]
    df = load_csv(csv)
    cut = int(len(df) * 2 / 3)
    train, test = df.iloc[:cut], df.iloc[cut:]
    print(f"Datos: {len(df)} velas | TRAIN {train.index[0]:%Y-%m-%d}→{train.index[-1]:%Y-%m-%d} "
          f"({len(train)}) | TEST {test.index[0]:%Y-%m-%d}→{test.index[-1]:%Y-%m-%d} ({len(test)})")

    results = []
    for bb_std, slm, width in itertools.product(*GRID.values()):
        p = StrategyParams(bb_std=bb_std, sl_atr_mult=slm, min_band_width_pips=width)
        s = run(train, p)
        if s["trades"] >= MIN_TRADES_TRAIN and s["profit_factor"] is not None:
            results.append((p, s))

    results.sort(key=lambda x: x[1]["profit_factor"], reverse=True)
    print(f"\n{'std':>4} {'slx':>4} {'ancho':>6} | {'PF tr':>6} {'ret% tr':>8} {'n tr':>5} "
          f"{'dd% tr':>7} | {'PF te':>6} {'ret% te':>8} {'n te':>5} {'dd% te':>7}")
    print("-" * 92)
    for p, s_train in results[:8]:
        s_test = run(test, p)
        pf_te = s_test["profit_factor"]
        print(f"{p.bb_std:>4} {p.sl_atr_mult:>4} {p.min_band_width_pips:>6} | "
              f"{s_train['profit_factor']:>6} {s_train['return_pct']:>8} {s_train['trades']:>5} "
              f"{s_train['max_drawdown_pct']:>7} | "
              f"{pf_te if pf_te is not None else '∞':>6} {s_test['return_pct']:>8} "
              f"{s_test['trades']:>5} {s_test['max_drawdown_pct']:>7}")

    # Baseline actual
    base = StrategyParams()
    bt, be = run(train, base), run(test, base)
    print(f"\nBaseline BB(20,2) SL1.5 sin filtro: "
          f"TRAIN PF {bt['profit_factor']} ret {bt['return_pct']}% | "
          f"TEST PF {be['profit_factor']} ret {be['return_pct']}%")


if __name__ == "__main__":
    main()
