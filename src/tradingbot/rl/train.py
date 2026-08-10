"""Entrenamiento y evaluación de FSRPPO.

``replay`` es la pieza central: recorre un tramo barra a barra con la política ya
entrenada y devuelve la curva de equity. Se usa tanto para evaluar el tramo de
test como para la pestaña de backtesting, de modo que **el simulador de
entrenamiento y el de backtest son el mismo objeto** y sus resultados son
directamente comparables.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from ..config import FsrParams, PpoParams
from ..metrics import Metrics, bars_per_year, evaluate
from .dataset import Dataset
from .env import EnvParams, FxTradingEnv, feature_scale_from_training, transaction_cost
from .ppo import IterationStats, PPOAgent
from .registry import ModelRecord, ModelRegistry

__all__ = [
    "ReplayResult",
    "replay",
    "buy_and_hold",
    "compare_with_benchmarks",
    "TrainingOutcome",
    "train",
]


@dataclass
class ReplayResult:
    equity: np.ndarray
    positions: np.ndarray
    metrics: Metrics
    trades: int
    total_cost: float

    def curve_points(self, timestamps) -> list[dict]:
        """Curva lista para la interfaz (una marca de tiempo por punto)."""
        return [
            {"time": str(t), "equity": round(float(e), 2), "position": int(p)}
            for t, e, p in zip(timestamps, self.equity[1:], self.positions)
        ]


def replay(
    agent: PPOAgent,
    dataset: Dataset,
    env_params: EnvParams | None = None,
    timeframe: str = "h1",
    deterministic: bool = True,
) -> ReplayResult:
    """Recorre el dataset completo con la política dada."""
    env = FxTradingEnv(dataset.features, dataset.prices, env_params or EnvParams())
    observation = env.reset(start=0)

    equity = [env.equity]
    positions: list[int] = []
    trades = 0
    total_cost = 0.0

    while True:
        action = agent.act(observation, deterministic=deterministic)
        observation, _reward, done, info = env.step(action)
        equity.append(info.equity)
        positions.append(info.position)
        if info.traded_units != 0:
            trades += 1
        total_cost += info.cost
        if done:
            break

    curve = np.asarray(equity)
    return ReplayResult(
        equity=curve,
        positions=np.asarray(positions),
        metrics=evaluate(curve, bars_per_year=bars_per_year(timeframe)),
        trades=trades,
        total_cost=total_cost,
    )


def buy_and_hold(
    dataset: Dataset, env_params: EnvParams | None = None, timeframe: str = "h1"
) -> ReplayResult:
    """Referencia pasiva: largo máximo en la primera barra y mantener.

    Es el listón que cualquier estrategia activa tiene que superar para
    justificar sus costes.
    """
    p = env_params or EnvParams()
    units = p.max_units
    prices = dataset.prices

    pnl = np.diff(prices) * units
    equity = np.concatenate(([p.initial_equity], p.initial_equity + np.cumsum(pnl)))
    coste_entrada = transaction_cost(units, p)
    equity[1:] -= coste_entrada  # el spread se paga una vez, al entrar

    return ReplayResult(
        equity=equity,
        positions=np.full(len(prices) - 1, units),
        metrics=evaluate(equity, bars_per_year=bars_per_year(timeframe)),
        trades=1,
        total_cost=coste_entrada,
    )


def compare_with_benchmarks(
    agent: PPOAgent,
    dataset: Dataset,
    candles,
    env_params: EnvParams | None = None,
    timeframe: str = "h1",
) -> list[dict]:
    """FSRPPO frente a Buy & Hold y a las estrategias por regla.

    Aviso metodológico que la interfaz debe respetar: FSRPPO y Buy & Hold se
    valoran **a mercado en cada barra**, mientras que ``run_backtest`` solo
    registra equity al cerrar cada operación. Sobre esa curva a saltos, la
    volatilidad y por tanto Sharpe, Calmar y Sortino no son comparables — se
    devuelven a ``None`` para las estrategias por regla en vez de publicar
    cifras que parecerían equivalentes sin serlo.
    """
    from ..backtest import run_backtest
    from ..config import RiskParams, StrategyParams
    from ..strategy import SIGNAL_STRATEGIES

    env_cfg = env_params or EnvParams()
    fsrppo = replay(agent, dataset, env_cfg, timeframe)
    referencia = buy_and_hold(dataset, env_cfg, timeframe)

    filas = [
        {"name": "FSRPPO", "basis": "per_bar", "trades": fsrppo.trades,
         **fsrppo.metrics.as_dict()},
        {"name": "Buy & Hold", "basis": "per_bar", "trades": referencia.trades,
         **referencia.metrics.as_dict()},
    ]

    tramo = candles.loc[dataset.timestamps[0]: dataset.timestamps[-1]]
    for nombre in sorted(SIGNAL_STRATEGIES):
        try:
            resultado = run_backtest(
                tramo,
                strategy_params=StrategyParams(active_strategy=nombre, timeframe=timeframe),
                risk=RiskParams(),
                initial_equity=env_cfg.initial_equity,
                spread_pips=env_cfg.effective_spread_pips,
            )
        except Exception as exc:  # una referencia rota no debe tumbar la comparativa
            filas.append({"name": nombre, "basis": "realised", "error": str(exc)})
            continue

        resumen = resultado.summary()
        filas.append({
            "name": nombre,
            "basis": "realised",
            "trades": resumen["trades"],
            "crr": resumen["return_pct"] / 100.0,
            "max_drawdown": abs(resumen["max_drawdown_pct"]) / 100.0,
            # Sin curva barra a barra no hay volatilidad comparable.
            "arr": None, "avr": None, "sharpe": None, "calmar": None, "sortino": None,
        })

    return filas


@dataclass
class TrainingOutcome:
    agent: PPOAgent
    record: ModelRecord
    history: list[IterationStats]
    train_replay: ReplayResult
    test_replay: ReplayResult
    benchmark: ReplayResult


def train(
    train_set: Dataset,
    test_set: Dataset,
    fsr_params: FsrParams | None = None,
    ppo_params: PpoParams | None = None,
    env_params: EnvParams | None = None,
    timeframe: str = "h1",
    instrument: str = "EUR/USD",
    registry: ModelRegistry | None = None,
    run_id: str | None = None,
    on_iteration: Callable[[IterationStats], None] | None = None,
) -> TrainingOutcome:
    """Entrena sobre ``train_set`` y evalúa sobre ``test_set``, sin mirarlo antes.

    El tramo de test no interviene en ninguna decisión del entrenamiento: ni en
    la selección de checkpoint ni en la parada. Es la única forma de que sus
    métricas signifiquen algo.
    """
    fsr = fsr_params or FsrParams()
    ppo = ppo_params or PpoParams()
    base_env = env_params or EnvParams()
    # No se calibra con validación/test: incluso una estadística tan sencilla
    # como la desviación estándar sería fuga de información futura.
    env_cfg = replace(
        base_env,
        feature_scale=feature_scale_from_training(train_set.features),
    )

    env = FxTradingEnv(train_set.features, train_set.prices, env_cfg)
    agent = PPOAgent(env.observation_size, ppo)
    history = agent.learn(env, on_iteration=on_iteration)

    train_replay = replay(agent, train_set, env_cfg, timeframe)
    test_replay = replay(agent, test_set, env_cfg, timeframe)
    benchmark = buy_and_hold(test_set, env_cfg, timeframe)

    reg = registry or ModelRegistry()
    record = ModelRecord(
        run_id=run_id or reg.new_run_id(),
        created_at=datetime.now(timezone.utc).isoformat(),
        instrument=instrument,
        timeframe=timeframe,
        train_range=[str(train_set.timestamps[0]), str(train_set.timestamps[-1])],
        test_range=[str(test_set.timestamps[0]), str(test_set.timestamps[-1])],
        fsr_params=asdict(fsr),
        ppo_params=asdict(ppo),
        env_params=asdict(env_cfg),
        train_metrics=train_replay.metrics.as_dict() | {"trades": train_replay.trades},
        test_metrics=test_replay.metrics.as_dict() | {"trades": test_replay.trades},
        benchmark_metrics=benchmark.metrics.as_dict() | {"strategy": "buy_and_hold"},
        feature_scale=env_cfg.feature_scale,
    )

    reg.save(record, agent.state_dict())
    from .export import export_policy

    export_policy(agent, reg.path_for(record.run_id) / "policy.npz")
    reg.save_history(record.run_id, [s.as_dict() for s in history])

    return TrainingOutcome(
        agent=agent,
        record=record,
        history=history,
        train_replay=train_replay,
        test_replay=test_replay,
        benchmark=benchmark,
    )
