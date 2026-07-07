"""Backtest de la estrategia Bollinger m15 sobre EUR/USD (CLI).

Fuentes de datos:
  --csv PATH     CSV genérico (time,open,high,low,close) o HistData M1
  --synthetic    random walk (solo para probar el pipeline, no mide rentabilidad)
  (por defecto)  descarga histórico real vía FXCM (requiere credenciales en .env)

La pestaña "Backtesting" del dashboard web hace esto mismo desde la interfaz.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradingbot.backtest import download_history, load_csv, run_backtest, synthetic_df
from tradingbot.config import load_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, help="ruta a CSV de velas")
    ap.add_argument("--synthetic", action="store_true", help="datos sintéticos (prueba de pipeline)")
    ap.add_argument("--months", type=int, default=24, help="meses de histórico FXCM")
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--spread", type=float, default=1.2, help="spread en pips")
    args = ap.parse_args()

    settings = load_settings()
    if args.csv:
        df = load_csv(args.csv)
        source = f"CSV {args.csv}"
    elif args.synthetic:
        df = synthetic_df()
        source = "SINTÉTICO (no representa el mercado real)"
    else:
        from tradingbot.broker import FxcmBroker

        broker = FxcmBroker(settings.fxcm)
        print(f"Conectando a FXCM ({settings.fxcm.connection}) para descargar histórico…")
        broker.connect()
        try:
            df = download_history(broker, args.months, ROOT / "data" / "history", progress=print)
        finally:
            broker.disconnect()
        source = f"FXCM {args.months} meses"

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
    pd.DataFrame([t.__dict__ for t in result.trades]).to_csv(out_dir / "backtest_trades.csv", index=False)
    result.equity_curve.to_csv(out_dir / "backtest_equity.csv", header=["equity"])
    print("\nDetalle: data/backtest_trades.csv y data/backtest_equity.csv")

    if args.synthetic:
        print("\n⚠️  Datos sintéticos: solo valida que el pipeline funciona.")
    else:
        s = result.summary()
        pf = s["profit_factor"]
        if pf is not None and pf < 1.0:
            print("\n⚠️  Profit factor < 1: NO operar con estos parámetros; recalibrar.")
        else:
            print("\nParámetros con expectativa positiva en el histórico probado.")


if __name__ == "__main__":
    main()
