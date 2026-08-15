"""Registro de modelos entrenados.

Cada entrenamiento deja una carpeta ``data/models/<run_id>/`` con los pesos, los
hiperparámetros con los que se obtuvieron y las métricas de train y test. El
archivo ``active.json`` marca cuáles usa el bot: promover un modelo es escribir
ahí su ``run_id``, y revertir es volver a cambiarlo.

``active.json`` es un **mapa de instrumento a modelo**, no un puntero único::

    {"EUR/USD": "fsrppo-20260809-223315", "XAU/USD": "fsrppo-20261101-101500"}

Cada modelo se entrena para un instrumento concreto y sus ``env_params`` llevan
la ficha de ese instrumento (pip, lote, spread), que es con la que se dimensionan
las órdenes. Un único activo global obligaba a elegir: al cambiar de símbolo el
bot se quedaba desarmado. Con el mapa, cambiar de símbolo cambia de modelo.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, normalize_symbol

__all__ = ["MODELS_DIR", "ModelRecord", "ModelRegistry", "meets_acceptance"]

MODELS_DIR = PROJECT_ROOT / "data" / "models"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _norm(symbol: str) -> str:
    """Clave del mapa. Normaliza para que ``eurusd`` y ``EUR/USD`` no se separen."""
    return normalize_symbol(symbol) if symbol else ""


@dataclass
class ModelRecord:
    run_id: str
    created_at: str
    instrument: str
    timeframe: str
    train_range: list[str]
    test_range: list[str]
    fsr_params: dict[str, Any]
    ppo_params: dict[str, Any]
    env_params: dict[str, Any]
    train_metrics: dict[str, Any]
    test_metrics: dict[str, Any]
    benchmark_metrics: dict[str, Any] = field(default_factory=dict)
    feature_scale: float = 1.0
    data_manifest: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def meets_acceptance(record: ModelRecord) -> bool:
    """Criterio informativo del proyecto; nunca bloquea la activación manual."""
    sharpe = float(record.test_metrics.get("sharpe", float("nan")))
    crr = float(record.test_metrics.get("crr", float("nan")))
    benchmark = float(record.benchmark_metrics.get("crr", float("nan")))
    return math.isfinite(sharpe) and sharpe > 0 and math.isfinite(crr) and crr > benchmark


class ModelRegistry:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else MODELS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self._lock = threading.RLock()

    # -- rutas ------------------------------------------------------------

    def path_for(self, run_id: str) -> Path:
        value = str(run_id)
        if not _RUN_ID.fullmatch(value) or value in {".", ".."}:
            raise ValueError(f"run_id inválido: {run_id!r}")
        path = (self.root / value).resolve()
        if path.parent != self.root:
            raise ValueError(f"run_id fuera del registro: {run_id!r}")
        return path

    @property
    def pointer_path(self) -> Path:
        return self.root / "active.json"

    @staticmethod
    def new_run_id(prefix: str = "fsrppo") -> str:
        if not _RUN_ID.fullmatch(prefix):
            raise ValueError(f"prefijo de run_id inválido: {prefix!r}")
        return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}"

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    # -- escritura --------------------------------------------------------

    def save(self, record: ModelRecord, state_dict: dict) -> Path:
        import torch

        destino = self.path_for(record.run_id)
        with self._lock:
            destino.mkdir(parents=True, exist_ok=True)
            temporal = destino / ".model.pt.tmp"
            torch.save(state_dict, temporal)
            os.replace(temporal, destino / "model.pt")
            self._atomic_text(
                destino / "meta.json",
                json.dumps(record.as_dict(), indent=2, ensure_ascii=False, default=str),
            )
        return destino

    def save_history(self, run_id: str, history: list[dict]) -> None:
        """Curvas de entrenamiento, para pintarlas en la interfaz."""
        with self._lock:
            path = self.path_for(run_id)
            path.mkdir(parents=True, exist_ok=True)
            self._atomic_text(path / "history.json", json.dumps(history))

    def delete(self, run_id: str) -> None:
        with self._lock:
            path = self.path_for(run_id)
            mapa = self.active_map()
            restante = {k: v for k, v in mapa.items() if v != run_id}
            if restante != mapa:
                self._write_pointer(restante)
            shutil.rmtree(path, ignore_errors=True)

    # -- lectura ----------------------------------------------------------

    def list(self) -> list[ModelRecord]:
        """Modelos registrados, del más reciente al más antiguo."""
        registros = []
        for meta in self.root.glob("*/meta.json"):
            try:
                registros.append(ModelRecord(**json.loads(meta.read_text())))
            except (json.JSONDecodeError, TypeError):
                # Una carpeta a medio escribir no debe tumbar el listado.
                continue
        return sorted(registros, key=lambda r: r.created_at, reverse=True)

    def get(self, run_id: str) -> ModelRecord | None:
        meta = self.path_for(run_id) / "meta.json"
        if not meta.exists():
            return None
        return ModelRecord(**json.loads(meta.read_text()))

    def history(self, run_id: str) -> list[dict]:
        archivo = self.path_for(run_id) / "history.json"
        return json.loads(archivo.read_text()) if archivo.exists() else []

    def load_state(self, run_id: str) -> dict:
        import torch

        pesos = self.path_for(run_id) / "model.pt"
        if not pesos.exists():
            raise FileNotFoundError(f"el modelo {run_id} no tiene pesos guardados")
        return torch.load(pesos, map_location="cpu", weights_only=True)

    # -- modelo activo ----------------------------------------------------

    def _write_pointer(self, mapa: dict[str, str]) -> None:
        """Escribe el mapa, o borra el archivo si queda vacío."""
        if mapa:
            self._atomic_text(
                self.pointer_path,
                json.dumps(mapa, indent=2, ensure_ascii=False, sort_keys=True),
            )
        elif self.pointer_path.exists():
            self.pointer_path.unlink()

    def active_map(self) -> dict[str, str]:
        """Mapa instrumento → ``run_id`` activo.

        Tolera el formato antiguo ``{"run_id": ...}``, que era un puntero global:
        se traduce leyendo con qué instrumento se entrenó ese modelo. Un
        ``active.json`` copiado de una versión anterior no debe tumbar el arranque.
        """
        if not self.pointer_path.exists():
            return {}
        try:
            datos = json.loads(self.pointer_path.read_text())
        except json.JSONDecodeError:
            return {}
        if not isinstance(datos, dict):
            return {}

        antiguo = datos.get("run_id")
        if isinstance(antiguo, str):
            record = self.get(antiguo)
            return {_norm(record.instrument): antiguo} if record else {}

        return {
            _norm(clave): valor
            for clave, valor in datos.items()
            if isinstance(clave, str) and isinstance(valor, str)
        }

    def activate(self, run_id: str) -> str:
        """Activa ``run_id`` para el instrumento con el que se entrenó.

        Devuelve ese instrumento, que no tiene por qué ser el que se está mirando
        en la interfaz: el modelo lleva su ficha dentro y activarlo para otro
        símbolo dimensionaría para uno y ejecutaría en otro.
        """
        model_dir = self.path_for(run_id)
        if not (model_dir / "policy.npz").exists() and not (model_dir / "model.pt").exists():
            raise FileNotFoundError(f"no existe el modelo {run_id}")
        record = self.get(run_id)
        if record is None:
            raise FileNotFoundError(f"el modelo {run_id} no tiene meta.json")

        instrumento = _norm(record.instrument)
        mapa = self.active_map()
        mapa[instrumento] = run_id
        self._write_pointer(mapa)
        return instrumento

    def deactivate(self, instrument: str | None = None) -> None:
        """Quita el activo de un instrumento; sin argumento, vacía el mapa."""
        if instrument is None:
            self._write_pointer({})
            return
        mapa = self.active_map()
        mapa.pop(_norm(instrument), None)
        self._write_pointer(mapa)

    def active_id(self, instrument: str | None = None) -> str | None:
        """``run_id`` activo para ese instrumento.

        Sin instrumento solo hay respuesta correcta cuando hay exactamente uno
        activo; con varios devuelve ``None`` en vez de elegir por su cuenta.
        """
        mapa = self.active_map()
        if instrument is None:
            return next(iter(mapa.values())) if len(mapa) == 1 else None
        return mapa.get(_norm(instrument))

    def active(self, instrument: str | None = None) -> ModelRecord | None:
        run_id = self.active_id(instrument)
        return self.get(run_id) if run_id else None
