"""Inferencia en vivo: del histórico de velas a una posición objetivo.

El bot en producción no tiene un ``FxTradingEnv`` —la posición y el equity los
da el bróker— pero la observación y el mapeo de acción a posición se construyen
con **las mismas funciones** que durante el entrenamiento (``build_observation``
y ``target_position`` de ``rl.env``), para que no pueda haber divergencia entre
lo que el agente aprendió y lo que ve al operar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import FsrParams
from ..fsr.represent import FsrResult, fsr_window
from .env import EnvParams, build_observation, target_position
from .export import load_numpy_policy
from .registry import ModelRegistry

__all__ = ["Decision", "FsrppoPolicy"]


@dataclass(frozen=True)
class Decision:
    """Lo que el agente propone para la barra recién cerrada."""

    action: np.ndarray
    target_position: int
    delta_units: int
    side: str                # "buy" | "sell" | "hold"
    price: float
    fsr: FsrResult

    @property
    def is_hold(self) -> bool:
        return self.delta_units == 0

    def as_dict(self) -> dict:
        return {
            "action": [round(float(a), 4) for a in self.action],
            "target_position": self.target_position,
            "delta_units": self.delta_units,
            "side": self.side,
            "price": self.price,
            "hursts": [round(float(h), 3) for h in self.fsr.hursts],
            "kept": [bool(k) for k in self.fsr.kept],
            "discarded_energy": round(self.fsr.discarded_energy, 4),
        }


class FsrppoPolicy:
    """Modelo entrenado listo para decidir sobre velas en vivo."""

    def __init__(
        self,
        agent,
        fsr_params: FsrParams,
        env_params: EnvParams,
        run_id: str | None = None,
    ):
        self.agent = agent
        self.fsr_params = fsr_params
        self.env_params = env_params
        self.run_id = run_id

    # -- carga -------------------------------------------------------------

    @classmethod
    def from_record(cls, registry: ModelRegistry, run_id: str) -> "FsrppoPolicy":
        """Reconstruye la política con los hiperparámetros con los que se entrenó.

        Se leen del registro y no de la configuración actual: si los ajustes del
        bot cambian, un modelo antiguo debe seguir viendo el mundo como cuando
        aprendió, o sus pesos dejan de significar lo que significaban.
        """
        record = registry.get(run_id)
        if record is None:
            raise FileNotFoundError(f"no existe el modelo {run_id}")

        fsr = FsrParams(**record.fsr_params)
        env = EnvParams(**record.env_params)
        artifact = registry.path_for(run_id) / "policy.npz"
        if artifact.exists():
            # Camino de produccion: no importa torch y funciona en la imagen
            # minima del bot.
            agent = load_numpy_policy(artifact)
        else:
            # Compatibilidad con modelos anteriores al formato policy.npz.
            from ..config import PpoParams
            from .ppo import PPOAgent

            ppo = PpoParams(
                **{**record.ppo_params, "hidden_sizes": tuple(record.ppo_params["hidden_sizes"])}
            )
            state = registry.load_state(run_id)
            agent = PPOAgent(int(state["observation_size"]), ppo)
            agent.load_state_dict(state)
        return cls(agent, fsr, env, run_id)

    @classmethod
    def load_active(cls, registry: ModelRegistry | None = None) -> "FsrppoPolicy | None":
        """Política del modelo marcado como activo, o ``None`` si no hay ninguno."""
        reg = registry or ModelRegistry()
        run_id = reg.active_id()
        if not run_id:
            return None
        try:
            return cls.from_record(reg, run_id)
        except (FileNotFoundError, ImportError, KeyError, OSError, TypeError, ValueError):
            return None

    # -- decisión ----------------------------------------------------------

    @property
    def required_bars(self) -> int:
        return self.fsr_params.window

    def decide(
        self,
        closes: np.ndarray,
        position: int = 0,
        entry_price: float = 0.0,
        equity: float | None = None,
        deterministic: bool = True,
    ) -> Decision:
        """Decide sobre la última barra cerrada de ``closes``.

        Solo se usan las ``window`` últimas barras: exactamente la misma ventana
        causal con la que se entrenó.
        """
        closes = np.asarray(closes, dtype=float)
        if closes.size < self.required_bars:
            raise ValueError(
                f"hacen falta {self.required_bars} cierres para decidir, hay {closes.size}"
            )

        ventana = closes[-self.required_bars:]
        price = float(ventana[-1])
        resultado = fsr_window(ventana, self.fsr_params)

        observation = build_observation(
            resultado.features,
            position,
            entry_price,
            price,
            self.env_params.initial_equity if equity is None else equity,
            self.env_params,
        )
        action = self.agent.act(observation, deterministic=deterministic)
        objetivo = target_position(action, position, price, self.env_params)
        delta = objetivo - position

        return Decision(
            action=action,
            target_position=objetivo,
            delta_units=delta,
            side="hold" if delta == 0 else ("buy" if delta > 0 else "sell"),
            price=price,
            fsr=resultado,
        )
