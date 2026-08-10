"""Registro de modelos entrenados.

Cada entrenamiento deja una carpeta ``data/models/<run_id>/`` con los pesos, los
hiperparámetros con los que se obtuvieron y las métricas de train y test. Un
puntero ``active.json`` marca cuál usa el bot: promover un modelo es cambiar ese
puntero, y revertir es volver a cambiarlo.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT

__all__ = ["MODELS_DIR", "ModelRecord", "ModelRegistry"]

MODELS_DIR = PROJECT_ROOT / "data" / "models"


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
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class ModelRegistry:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else MODELS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    # -- rutas ------------------------------------------------------------

    def path_for(self, run_id: str) -> Path:
        return self.root / run_id

    @property
    def pointer_path(self) -> Path:
        return self.root / "active.json"

    @staticmethod
    def new_run_id(prefix: str = "fsrppo") -> str:
        return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"

    # -- escritura --------------------------------------------------------

    def save(self, record: ModelRecord, state_dict: dict) -> Path:
        import torch

        destino = self.path_for(record.run_id)
        destino.mkdir(parents=True, exist_ok=True)
        torch.save(state_dict, destino / "model.pt")
        (destino / "meta.json").write_text(
            json.dumps(record.as_dict(), indent=2, ensure_ascii=False, default=str)
        )
        return destino

    def save_history(self, run_id: str, history: list[dict]) -> None:
        """Curvas de entrenamiento, para pintarlas en la interfaz."""
        (self.path_for(run_id)).mkdir(parents=True, exist_ok=True)
        (self.path_for(run_id) / "history.json").write_text(json.dumps(history))

    def delete(self, run_id: str) -> None:
        if self.active_id() == run_id:
            if self.pointer_path.exists():
                self.pointer_path.unlink()
        shutil.rmtree(self.path_for(run_id), ignore_errors=True)

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
        return torch.load(pesos, map_location="cpu", weights_only=False)

    # -- modelo activo ----------------------------------------------------

    def activate(self, run_id: str) -> None:
        model_dir = self.path_for(run_id)
        if not (model_dir / "policy.npz").exists() and not (model_dir / "model.pt").exists():
            raise FileNotFoundError(f"no existe el modelo {run_id}")
        self.pointer_path.write_text(json.dumps({"run_id": run_id}))

    def deactivate(self) -> None:
        if self.pointer_path.exists():
            self.pointer_path.unlink()

    def active_id(self) -> str | None:
        if not self.pointer_path.exists():
            return None
        try:
            return json.loads(self.pointer_path.read_text()).get("run_id")
        except json.JSONDecodeError:
            return None

    def active(self) -> ModelRecord | None:
        run_id = self.active_id()
        return self.get(run_id) if run_id else None
