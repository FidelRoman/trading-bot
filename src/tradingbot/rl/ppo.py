"""PPO — Proximal Policy Optimization (Algoritmo 1 del paper).

Implementa el bucle publicado: ``NI`` iteraciones, cada una recogiendo ``NE``
episodios de ``T`` pasos, calculando la ventaja por GAE y actualizando política
y valor con el objetivo recortado más regularización por entropía
(ecuaciones 5 a 10).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from ..config import PpoParams
from .env import FxTradingEnv
from .networks import PolicyNet, ValueNet, as_tensor

__all__ = ["Rollout", "IterationStats", "PPOAgent"]


@dataclass
class Rollout:
    """Transiciones de una iteración, ya aplanadas en un solo lote."""

    observations: torch.Tensor
    actions: torch.Tensor
    log_probs: torch.Tensor
    advantages: torch.Tensor
    returns: torch.Tensor
    episode_rewards: list[float] = field(default_factory=list)
    final_equities: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return self.observations.shape[0]


@dataclass
class IterationStats:
    iteration: int
    mean_reward: float
    mean_equity: float
    policy_loss: float
    value_loss: float
    entropy: float

    def as_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "mean_reward": self.mean_reward,
            "mean_equity": self.mean_equity,
            "policy_loss": self.policy_loss,
            "value_loss": self.value_loss,
            "entropy": self.entropy,
        }


class PPOAgent:
    """Agente PPO con redes de política y valor independientes."""

    def __init__(self, observation_size: int, params: PpoParams | None = None,
                 action_size: int = 2):
        self.params = params or PpoParams()
        torch.manual_seed(self.params.seed)
        # RNG propio: usar el global de numpy haría que el orden de los minilotes
        # —y por tanto el entrenamiento— dependiese de qué se haya ejecutado antes
        # en el mismo proceso, y `seed` dejaría de reproducir nada.
        self._rng = np.random.default_rng(self.params.seed)

        self.policy = PolicyNet(observation_size, action_size, self.params.hidden_sizes)
        self.value = ValueNet(observation_size, self.params.hidden_sizes)
        self.policy_optimizer = torch.optim.Adam(
            self.policy.parameters(), lr=self.params.learning_rate
        )
        self.value_optimizer = torch.optim.Adam(
            self.value.parameters(), lr=self.params.learning_rate
        )
        self.observation_size = observation_size

    # -- recogida de experiencia -----------------------------------------

    @torch.no_grad()
    def collect(self, env: FxTradingEnv, rng: np.random.Generator) -> Rollout:
        """Recoge ``NE`` episodios de ``T`` pasos empezando en puntos aleatorios.

        Arrancar cada episodio en una barra distinta expone al agente a
        regímenes de mercado variados dentro del mismo tramo de entrenamiento;
        empezar siempre en la primera barra le haría memorizar una sola historia.
        """
        p = self.params
        last_start = env.features.shape[0] - 1
        obs_batch, act_batch, logp_batch = [], [], []
        adv_batch, ret_batch = [], []
        episode_rewards, final_equities = [], []

        for _ in range(p.episodes_per_iteration):
            highest = max(1, last_start - p.steps_per_episode)
            start = int(rng.integers(0, highest))
            observation = env.reset(start=start, length=p.steps_per_episode)

            observations, actions, log_probs, rewards, values, dones = [], [], [], [], [], []

            for _ in range(p.steps_per_episode):
                tensor = as_tensor(observation).unsqueeze(0)
                action, log_prob = self.policy.act(tensor)
                value = self.value(tensor)

                observations.append(observation)
                actions.append(action.squeeze(0).numpy())
                log_probs.append(float(log_prob))
                values.append(float(value))

                observation, reward, done, _info = env.step(action.squeeze(0).numpy())
                rewards.append(reward)
                dones.append(done)
                if done:
                    break

            bootstrap = 0.0 if dones[-1] else float(self.value(as_tensor(observation).unsqueeze(0)))
            advantages, returns = self._gae(
                np.asarray(rewards), np.asarray(values), bootstrap
            )

            obs_batch.append(np.asarray(observations, dtype=np.float32))
            act_batch.append(np.asarray(actions, dtype=np.float32))
            logp_batch.append(np.asarray(log_probs, dtype=np.float32))
            adv_batch.append(advantages)
            ret_batch.append(returns)
            episode_rewards.append(float(np.sum(rewards)))
            final_equities.append(float(env.equity))

        advantages = np.concatenate(adv_batch)
        # Normalizar la ventaja estabiliza el paso de gradiente cuando las
        # recompensas están en unidades monetarias y su escala varía por episodio.
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        return Rollout(
            observations=as_tensor(np.concatenate(obs_batch)),
            actions=as_tensor(np.concatenate(act_batch)),
            log_probs=as_tensor(np.concatenate(logp_batch)),
            advantages=as_tensor(advantages),
            returns=as_tensor(np.concatenate(ret_batch)),
            episode_rewards=episode_rewards,
            final_equities=final_equities,
        )

    def _gae(self, rewards: np.ndarray, values: np.ndarray, bootstrap: float):
        """Ventaja generalizada, ecuación (6), y retorno descontado ``U_t``."""
        p = self.params
        steps = len(rewards)
        advantages = np.zeros(steps, dtype=np.float32)
        running = 0.0
        next_value = bootstrap

        for t in reversed(range(steps)):
            delta = rewards[t] + p.gamma * next_value - values[t]
            running = delta + p.gamma * p.gae_lambda * running
            advantages[t] = running
            next_value = values[t]

        return advantages, (advantages + values).astype(np.float32)

    # -- actualización ----------------------------------------------------

    def update(self, rollout: Rollout) -> tuple[float, float, float]:
        """Optimiza L_π (ecuación 9) y L_V (ecuación 10) sobre el lote."""
        p = self.params
        total = len(rollout)
        indices = np.arange(total)
        policy_losses, value_losses, entropies = [], [], []

        for _ in range(p.update_epochs):
            self._rng.shuffle(indices)
            for start in range(0, total, p.minibatch_size):
                batch = indices[start : start + p.minibatch_size]
                if batch.size < 2:
                    continue

                observations = rollout.observations[batch]
                actions = rollout.actions[batch]
                advantages = rollout.advantages[batch]

                log_probs, entropy = self.policy.evaluate(observations, actions)
                ratio = torch.exp(log_probs - rollout.log_probs[batch])

                # Ecuación (5): mínimo entre el objetivo sin recortar y el recortado.
                unclipped = ratio * advantages
                clipped = torch.clamp(ratio, 1 - p.clip_epsilon, 1 + p.clip_epsilon) * advantages
                # L_π se maximiza; el optimizador minimiza, de ahí el signo.
                policy_loss = -(torch.min(unclipped, clipped).mean()
                                + p.entropy_coef * entropy.mean())

                self.policy_optimizer.zero_grad()
                policy_loss.backward()
                nn.utils.clip_grad_norm_(self.policy.parameters(), p.max_grad_norm)
                self.policy_optimizer.step()

                value_loss = nn.functional.mse_loss(
                    self.value(observations), rollout.returns[batch]
                )
                self.value_optimizer.zero_grad()
                value_loss.backward()
                nn.utils.clip_grad_norm_(self.value.parameters(), p.max_grad_norm)
                self.value_optimizer.step()

                policy_losses.append(policy_loss.detach().item())
                value_losses.append(value_loss.detach().item())
                entropies.append(entropy.detach().mean().item())

        return (
            float(np.mean(policy_losses)) if policy_losses else 0.0,
            float(np.mean(value_losses)) if value_losses else 0.0,
            float(np.mean(entropies)) if entropies else 0.0,
        )

    # -- bucle completo ---------------------------------------------------

    def learn(self, env: FxTradingEnv, iterations: int | None = None,
              on_iteration=None) -> list[IterationStats]:
        """Ejecuta el bucle del Algoritmo 1 y devuelve el historial por iteración."""
        rng = self._rng
        total = iterations if iterations is not None else self.params.iterations
        history: list[IterationStats] = []

        for k in range(1, total + 1):
            rollout = self.collect(env, rng)
            policy_loss, value_loss, entropy = self.update(rollout)

            stats = IterationStats(
                iteration=k,
                mean_reward=float(np.mean(rollout.episode_rewards)),
                mean_equity=float(np.mean(rollout.final_equities)),
                policy_loss=policy_loss,
                value_loss=value_loss,
                entropy=entropy,
            )
            history.append(stats)
            if on_iteration is not None:
                on_iteration(stats)

        return history

    # -- inferencia -------------------------------------------------------

    @torch.no_grad()
    def act(self, observation: np.ndarray, deterministic: bool = True) -> np.ndarray:
        action, _ = self.policy.act(as_tensor(observation).unsqueeze(0), deterministic)
        return action.squeeze(0).numpy()

    def state_dict(self) -> dict:
        return {
            "policy": self.policy.state_dict(),
            "value": self.value.state_dict(),
            "observation_size": self.observation_size,
        }

    def load_state_dict(self, state: dict) -> None:
        self.policy.load_state_dict(state["policy"])
        self.value.load_state_dict(state["value"])
