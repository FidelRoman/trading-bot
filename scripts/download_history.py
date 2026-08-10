"""Descarga histórico FXCM para varias combinaciones de símbolo y timeframe.

Este script es deliberadamente autónomo: corre con Python 3.7 y el wheel Linux
antiguo de ForexConnect, mientras la aplicación principal requiere Python 3.10.
"""
from __future__ import print_function

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


TIMEFRAMES = {
    "m1": "m1",
    "m5": "m5",
    "m15": "m15",
    "m30": "m30",
    "h1": "H1",
    "h4": "H4",
    "d1": "D1",
}


def comma_list(value):
    items = []
    for raw in value.split(","):
        item = raw.strip()
        if item and item not in items:
            items.append(item)
    if not items:
        raise argparse.ArgumentTypeError("se requiere al menos un valor")
    return items


def symbol_slug(symbol):
    return symbol.replace("/", "").lower()


def history_filename(symbol, timeframe, date_from, date_to):
    return "{}_{}_{:%Y%m%d}_{:%Y%m%d}.csv".format(
        symbol_slug(symbol), timeframe.lower(), date_from, date_to
    )


def years_ago(moment, years):
    try:
        return moment.replace(year=moment.year - years)
    except ValueError:
        return moment.replace(year=moment.year - years, day=28)


def _credentials_from_env():
    user = os.getenv("FXCM_USER", "")
    password = os.getenv("FXCM_PASS", "")
    if not user or not password:
        raise RuntimeError("FXCM_USER y FXCM_PASS son obligatorios")
    return {
        "user": user,
        "password": password,
        "connection": os.getenv("FXCM_CONNECTION", "Demo"),
        "url": os.getenv("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp"),
    }


class FxcmHistorySession(object):
    def __init__(self, credentials):
        self.credentials = credentials
        self.fx = None

    def connect(self):
        from forexconnect import ForexConnect

        self.fx = ForexConnect()
        self.fx.login(
            self.credentials["user"],
            self.credentials["password"],
            self.credentials["url"],
            self.credentials["connection"],
            None,
            None,
        )

    def disconnect(self):
        if self.fx is not None:
            try:
                self.fx.logout()
            finally:
                self.fx = None

    def candles(self, symbol, timeframe, date_from=None, date_to=None, count=0):
        if self.fx is None:
            raise RuntimeError("la sesión FXCM no está conectada")
        import pandas as pd

        raw = self.fx.get_history(
            symbol, TIMEFRAMES[timeframe.lower()], date_from, date_to, count
        )
        frame = pd.DataFrame(raw)
        if frame.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        frame["Date"] = pd.to_datetime(frame["Date"], utc=True)
        frame = frame.set_index("Date").sort_index()
        result = frame[["BidOpen", "BidHigh", "BidLow", "BidClose", "Volume"]].rename(
            columns={
                "BidOpen": "open",
                "BidHigh": "high",
                "BidLow": "low",
                "BidClose": "close",
                "Volume": "volume",
            }
        )
        result.index.name = "time"
        return result


def download_range(session, symbol, timeframe, date_from, date_to, chunk_days=90):
    import pandas as pd

    chunks = []
    cursor = date_from
    while cursor < date_to:
        chunk_end = min(cursor + timedelta(days=chunk_days), date_to)
        print("  {:%Y-%m-%d} -> {:%Y-%m-%d}".format(cursor, chunk_end))
        chunk = session.candles(symbol, timeframe, cursor, chunk_end, count=0)
        if not chunk.empty:
            chunks.append(chunk)
        cursor = chunk_end
    if not chunks:
        raise RuntimeError("FXCM no devolvió velas para {} {}".format(symbol, timeframe))
    frame = pd.concat(chunks)
    return frame[~frame.index.duplicated(keep="first")].sort_index()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=comma_list, required=True)
    parser.add_argument("--timeframes", type=comma_list, required=True)
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("data/history"))
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="trae las últimas N velas; se usa para el smoke test",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.years <= 0:
        raise SystemExit("--years debe ser mayor que cero")
    invalid = [tf for tf in args.timeframes if tf.lower() not in TIMEFRAMES]
    if invalid:
        raise SystemExit("timeframes no soportados: {}".format(", ".join(invalid)))

    end = datetime.now(timezone.utc)
    start = years_ago(end, args.years)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = FxcmHistorySession(_credentials_from_env())
    session.connect()
    try:
        for symbol in args.symbols:
            for raw_timeframe in args.timeframes:
                timeframe = raw_timeframe.lower()
                print("Descargando {} {}".format(symbol, timeframe))
                if args.count:
                    frame = session.candles(symbol, timeframe, count=args.count)
                    if frame.empty:
                        raise RuntimeError(
                            "FXCM no devolvió velas para {} {}".format(symbol, timeframe)
                        )
                    file_start = frame.index[0].to_pydatetime()
                    file_end = frame.index[-1].to_pydatetime()
                else:
                    frame = download_range(session, symbol, timeframe, start, end)
                    file_start, file_end = start, end
                path = args.output_dir / history_filename(
                    symbol, timeframe, file_start, file_end
                )
                frame.to_csv(path)
                print("  {} ({} velas)".format(path, len(frame)))
    finally:
        session.disconnect()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("error: {}".format(exc), file=sys.stderr)
        sys.exit(1)
