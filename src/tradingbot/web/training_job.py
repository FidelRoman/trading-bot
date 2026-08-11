"""Entrenamiento y precálculo de FSR en segundo plano.

Mismo patrón que ``backtest_job.py``: un solo trabajo a la vez, estado
consultable y progreso emitido por WebSocket. Entrenar bloquea durante minutos,
así que no puede correr en el bucle de eventos.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..backtest import load_csv
from ..config import PROJECT_ROOT, FsrParams, PpoParams
from ..rl.dataset import build_dataset
from ..rl.env import EnvParams
from ..rl.registry import ModelRegistry

log = logging.getLogger(__name__)

HISTORY_DIR = PROJECT_ROOT / "data" / "history"

__all__ = ["TrainingJob"]


class TrainingJob:
    """Ejecuta un entrenamiento (o un precálculo de FSR) en un hilo aparte."""

    def __init__(self, store, notify=None):
        self.store = store
        self.notify = notify            # callable(dict) -> None, para el WebSocket
        self._lock = threading.Lock()
        self._running = False
        self._kind = ""
        self._note = ""
        self._progress = 0.0
        self._curve: list[dict] = []

    # -- estado ------------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            if self._running:
                return {
                    "status": "running",
                    "kind": self._kind,
                    "note": self._note,
                    "progress": round(self._progress, 4),
                    "curve": self._curve[-400:],
                }
        last = self.store.get_state("last_training")
        return last or {"status": "idle"}

    def _set(self, note: str, progress: float | None = None) -> None:
        with self._lock:
            self._note = note
            if progress is not None:
                self._progress = progress
        if self.notify:
            self.notify({"type": "training", **self.state()})

    def _claim(self, kind: str) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running, self._kind = True, kind
            self._note, self._progress, self._curve = "Preparando…", 0.0, []
            return True

    def _release(self, result: dict) -> None:
        self.store.set_state("last_training", result)
        with self._lock:
            self._running = False
        if self.notify:
            self.notify({"type": "training", **result})

    # -- datos -------------------------------------------------------------

    @staticmethod
    def available_datasets() -> list[dict]:
        if not HISTORY_DIR.exists():
            return []
        return sorted(
            ({"name": p.name, "size": p.stat().st_size} for p in HISTORY_DIR.glob("*.csv")),
            key=lambda d: d["name"],
        )

    def _load_candles(self, csv_name: str | None, timeframe: str) -> pd.DataFrame:
        if csv_name:
            ruta = HISTORY_DIR / Path(csv_name).name
            if not ruta.exists():
                raise FileNotFoundError(f"no existe el histórico {csv_name}")
        else:
            candidatos = sorted(HISTORY_DIR.glob(f"*{timeframe.lower()}*.csv"))
            if not candidatos:
                raise FileNotFoundError("no hay histórico descargado en data/history")
            ruta = candidatos[-1]
        return load_csv(ruta, timeframe=timeframe)

    # -- precálculo de FSR -------------------------------------------------

    def run_precompute(self, csv_name: str | None, timeframe: str, params: FsrParams) -> dict:
        empezado = datetime.now(timezone.utc)
        try:
            candles = self._load_candles(csv_name, timeframe)
            self._set(f"Calculando FSR de {len(candles)} barras…", 0.0)

            def progreso(hechas: int, totales: int) -> None:
                self._set(f"FSR {hechas}/{totales}", hechas / totales)

            dataset = build_dataset(candles, params, progress=progreso)
            resultado = {
                "status": "done",
                "kind": "precompute",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round((datetime.now(timezone.utc) - empezado).total_seconds(), 1),
                "bars": len(dataset),
                "window": params.window,
            }
        except Exception as exc:
            log.exception("precálculo de FSR")
            resultado = {"status": "error", "kind": "precompute", "error": str(exc)}
        self._release(resultado)
        return resultado

    # -- entrenamiento -----------------------------------------------------

    def run_training(
        self,
        csv_name: str | None,
        timeframe: str,
        train_end: str | None,
        fsr: FsrParams,
        ppo: PpoParams,
        env: EnvParams,
        instrument: str = "EUR/USD",
        activate: bool = False,
    ) -> dict:
        empezado = datetime.now(timezone.utc)
        try:
            # Importacion diferida: la imagen de produccion no instala torch ni
            # expone entrenamiento; la API y la inferencia siguen arrancando.
            from ..rl.train import buy_and_hold, train

            candles = self._load_candles(csv_name, timeframe)
            self._set("Preparando características FSR…", 0.0)

            def progreso_fsr(hechas: int, totales: int) -> None:
                self._set(f"FSR {hechas}/{totales}", hechas / totales)

            dataset = build_dataset(candles, fsr, progress=progreso_fsr)
            corte = train_end or dataset.timestamps[int(len(dataset) * 0.75)]
            entrena, evalua = dataset.split(corte)

            self._set(f"Entrenando sobre {len(entrena)} barras…", 0.0)

            def por_iteracion(stats) -> None:
                with self._lock:
                    self._curve.append(stats.as_dict())
                self._set(
                    f"Iteración {stats.iteration}/{ppo.iterations}",
                    stats.iteration / ppo.iterations,
                )

            salida = train(
                entrena, evalua,
                fsr_params=fsr, ppo_params=ppo, env_params=env,
                timeframe=timeframe, instrument=instrument, on_iteration=por_iteracion,
            )

            registro = ModelRegistry()
            if activate:
                registro.activate(salida.record.run_id)

            referencia = buy_and_hold(evalua, env, timeframe)
            resultado = {
                "status": "done",
                "kind": "training",
                "run_id": salida.record.run_id,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round((datetime.now(timezone.utc) - empezado).total_seconds(), 1),
                "train_metrics": salida.record.train_metrics,
                "test_metrics": salida.record.test_metrics,
                "benchmark_metrics": referencia.metrics.as_dict(),
                "activated": activate,
                "curve": [s.as_dict() for s in salida.history],
            }
        except Exception as exc:
            log.exception("entrenamiento")
            resultado = {"status": "error", "kind": "training", "error": str(exc)}
        self._release(resultado)
        return resultado

    # -- descarga de histórico ---------------------------------------------

    def run_download(self, broker, symbol: str, timeframe: str, years: int) -> dict:
        """Descarga histórico de FXCM al CSV que luego consume el entrenamiento.

        Va por la sesión que el bróker ya tiene autenticada, pidiéndole otro
        símbolo: abrir un segundo login contra FXCM mientras el bot opera podría
        tumbarle la sesión de trading.

        Se pide en trozos porque FXCM acota cuántas velas devuelve por llamada;
        el nombre del archivo sigue el formato de ``scripts/download_history.py``
        para que ambos caminos produzcan lo mismo.
        """
        from datetime import timedelta

        empezado = datetime.now(timezone.utc)
        try:
            if not getattr(broker, "connected", False):
                raise RuntimeError("El bróker no está conectado a FXCM")
            if not hasattr(broker, "get_candles"):
                raise RuntimeError("El bróker no expone histórico")

            hasta = datetime.now(timezone.utc)
            try:
                desde = hasta.replace(year=hasta.year - years)
            except ValueError:                      # 29 de febrero
                desde = hasta.replace(year=hasta.year - years, day=28)

            trozos: list[pd.DataFrame] = []
            total_dias = max((hasta - desde).days, 1)
            cursor = desde
            while cursor < hasta:
                fin = min(cursor + timedelta(days=90), hasta)
                self._set(
                    f"{symbol} {timeframe.upper()}: {cursor:%Y-%m-%d} → {fin:%Y-%m-%d}",
                    (cursor - desde).days / total_dias,
                )
                trozo = broker.get_candles(
                    count=0, date_from=cursor, date_to=fin,
                    timeframe=timeframe, symbol=symbol,
                )
                if trozo is not None and not trozo.empty:
                    trozos.append(trozo)
                cursor = fin

            if not trozos:
                raise RuntimeError(
                    f"FXCM no devolvió velas de {symbol} {timeframe}. "
                    "¿Está el instrumento suscrito en estado T?"
                )
            marco = pd.concat(trozos)
            marco = marco[~marco.index.duplicated(keep="first")].sort_index()

            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            nombre = "{}_{}_{:%Y%m%d}_{:%Y%m%d}.csv".format(
                symbol.replace("/", "").lower(), timeframe.lower(), desde, hasta
            )
            marco.to_csv(HISTORY_DIR / nombre)

            resultado = {
                "status": "done",
                "kind": "download",
                "dataset": nombre,
                "symbol": symbol,
                "timeframe": timeframe,
                "bars": int(len(marco)),
                "first_bar": str(marco.index[0]),
                "last_bar": str(marco.index[-1]),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round((datetime.now(timezone.utc) - empezado).total_seconds(), 1),
            }
        except Exception as exc:
            log.exception("descarga de histórico")
            resultado = {"status": "error", "kind": "download", "error": str(exc)}
        self._release(resultado)
        return resultado

    # -- lanzadores --------------------------------------------------------

    def start_download(self, **kwargs) -> bool:
        if not self._claim("download"):
            return False
        threading.Thread(target=self.run_download, kwargs=kwargs, daemon=True).start()
        return True

    def start_precompute(self, **kwargs) -> bool:
        if not self._claim("precompute"):
            return False
        threading.Thread(target=self.run_precompute, kwargs=kwargs, daemon=True).start()
        return True

    def start_training(self, **kwargs) -> bool:
        if not self._claim("training"):
            return False
        threading.Thread(target=self.run_training, kwargs=kwargs, daemon=True).start()
        return True
