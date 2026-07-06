"""Backtest de la estrategia Bollinger m15 sobre EUR/USD.

Fuentes de datos (en orden de preferencia):
  --csv PATH     CSV genérico (time,open,high,low,close) o HistData M1
  --synthetic    random walk (solo para probar el pipeline, no mide rentabilidad)
  (por defecto)  descarga histórico real vía FXCM (requiere credenciales en .env)

Ejemplos:
  uv run python scripts/run_backtest.py --months 24
  uv run python scripts/run_backtest.py --csv data/history/eurusd_m1.csv
  uv run python scripts/run_backtest.py --synthetic
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradingbot.backtest import load_csv, run_backtest
from tradingbot.config import load_settings


def synthetic_df(days: int = 365) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = days * 96  # velas m15
    steps = rng.normal(0, 0.00035, n) + 0.000002 * np.sin(np.arange(n) / 200)
    close = 1.08 + np.cumsum(steps)
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="15min")
    high = close + np.abs(rng.normal(0, 0.0002, n))
    low = close - np.abs(rng.normal(0, 0.0002, n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def fxcm_df(months: int) -> pd.DataFrame:
    from tradingbot.broker import FxcmBroker

    settings = load_settings()
    broker = FxcmBroker(settings.fxcm)
    print(f"Conectando a FXCM ({settings.fxcm.connection}) para descargar histórico…")
    broker.connect()
    try:
        chunks = []
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=months * 30)
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=90), end)
            print(f"  {cursor:%Y-%m-%d} → {chunk_end:%Y-%m-%d}")
            chunks.append(broker.get_candles(count=0, date_from=cursor, date_to=chunk_end))
            cursor = chunk_end
        df = pd.concat(chunks)
        df = df[~df.index.duplicated(keep="first")].sort_index()
        cache = ROOT / "data" / "history"
        cache.mkdir(parents=True, exist_ok=True)
        out = cache / f"eurusd_m15_{months}m.csv"
        df.to_csv(out)
        print(f"Histórico guardado en {out} ({len(df)} velas)")
        return df[["open", "high", "low", "close"]]
    finally:
        broker.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, help="ruta a CSV de velas")
    ap.add_argument("--synthetic", action="store_true", help="datos sintéticos (prueba de pipeline)")
    ap.add_argument("--months", type=int, default=24, help="meses de histórico FXCM")
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--spread", type=float, default=1.2, help="spread en pips")
    args = ap.parse_args()

    if args.csv:
        df = load_csv(args.csv)
        source = f"CSV {args.csv}"
    elif args.synthetic:
        df = synthetic_df()
        source = "SINTÉTICO (no representa el mercado real)"
    else:
        df = fxcm_df(args.months)
        source = f"FXCM {args.months} meses"

    settings = load_settings()
    print(f"\nBacktest sobre {len(df)} velas m15 — fuente: {source}")
    result = run_backtest(
        df,
        strategy_params=settings.strategy,
        risk=settings.risk,
        initial_equity=args.equity,
        spread_pips=args.spread,
    )

    print("\n=== RESULTADOS ===")
    for k, v in result.summary().items():
        print(f"  {k:18s} {v}")

    out_dir = ROOT / "data"
    trades_df = pd.DataFrame([t.__dict__ for t in result.trades])
    trades_df.to_csv(out_dir / "backtest_trades.csv", index=False)
    result.equity_curve.to_csv(out_dir / "backtest_equity.csv", header=["equity"])
    print(f"\nDetalle: data/backtest_trades.csv y data/backtest_equity.csv")

    if args.synthetic:
        print("\n⚠️  Datos sintéticos: solo valida que el pipeline funciona.")
    else:
        s = result.summary()
        if s["profit_factor"] < 1.0:
            print("\n⚠️  Profit factor < 1: NO operar con estos parámetros; recalibrar.")
        else:
            print("\nParámetros con expectativa positiva en el histórico probado.")


if __name__ == "__main__":
    main()
