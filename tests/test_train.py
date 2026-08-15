"""Tests del dataset, el registro de modelos y el ciclo de entrenamiento."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.config import FsrParams, PpoParams
from tradingbot.rl.dataset import Dataset, build_dataset
from tradingbot.rl.env import EnvParams, feature_scale_from_training
from tradingbot.rl.ppo import PPOAgent
from tradingbot.rl.registry import ModelRecord, ModelRegistry
from tradingbot.rl.selection import rank_markets
from tradingbot.rl.train import buy_and_hold, replay, train


def velas(n: int = 200, inicio: str = "2025-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = 1.08 + np.cumsum(rng.standard_normal(n)) * 2e-4
    idx = pd.date_range(inicio, periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": close + 1e-4, "low": close - 1e-4, "close": close}, index=idx
    )


def dataset_sintetico(n: int = 120) -> Dataset:
    prices = 1.08 + np.cumsum(np.random.default_rng(9).standard_normal(n)) * 2e-4
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    features = np.zeros((n, 8), dtype=np.float32)
    return Dataset(idx, prices, features)


# -- dataset ---------------------------------------------------------------


def test_build_dataset_descarta_las_barras_sin_ventana_completa(tmp_path):
    params = FsrParams(window=20, ensemble_size=3)
    candles = velas(80)

    ds = build_dataset(candles, params, cache_dir=tmp_path, workers=1)

    assert len(ds) == 80 - params.window + 1
    # La primera barra representable es la que cierra la primera ventana completa.
    assert ds.timestamps[0] == candles.index[params.window - 1]
    assert ds.prices[0] == pytest.approx(candles["close"].iloc[params.window - 1])


def test_el_dataset_rechaza_componentes_desalineados():
    idx = pd.date_range("2025-01-01", periods=10, freq="h", tz="UTC")
    with pytest.raises(ValueError, match="desalineado"):
        Dataset(idx, np.zeros(10), np.zeros((9, 4), dtype=np.float32))


def test_split_parte_por_fecha_sin_solapar_barras():
    ds = dataset_sintetico(120)
    corte = ds.timestamps[70]

    entrena, evalua = ds.split(corte)

    assert len(entrena) + len(evalua) == len(ds)
    assert entrena.timestamps[-1] <= corte < evalua.timestamps[0]
    # Ninguna barra aparece en los dos tramos.
    assert set(entrena.timestamps).isdisjoint(set(evalua.timestamps))


def test_split_rechaza_un_corte_que_deja_un_tramo_vacio():
    ds = dataset_sintetico(60)
    with pytest.raises(ValueError, match="tramo vacío"):
        ds.split("2030-01-01")


def test_split_three_way_respeta_60_20_20_y_el_orden_cronologico():
    ds = dataset_sintetico(100)

    entrena, valida, test = ds.split_three_way()

    assert (len(entrena), len(valida), len(test)) == (60, 20, 20)
    assert entrena.timestamps[-1] < valida.timestamps[0] < test.timestamps[0]
    assert set(entrena.timestamps).isdisjoint(valida.timestamps)
    assert set(valida.timestamps).isdisjoint(test.timestamps)


def test_feature_scale_depende_solo_de_train():
    train_features = np.array([[0.0, 0.01], [-0.01, 0.02]], dtype=np.float32)
    test_a = np.full((10, 2), 1e-6, dtype=np.float32)
    test_b = np.full((10, 2), 1e6, dtype=np.float32)

    escala_a = feature_scale_from_training(train_features)
    escala_b = feature_scale_from_training(train_features)

    assert escala_a == pytest.approx(1 / np.std(train_features))
    assert escala_b == escala_a
    assert escala_a != pytest.approx(1 / np.std(np.concatenate([train_features, test_a])))
    assert escala_a != pytest.approx(1 / np.std(np.concatenate([train_features, test_b])))


def test_el_tramo_de_test_no_influye_en_la_seleccion():
    candidates = [
        {
            "symbol": "EUR/USD", "timeframe": "h4",
            "validation": {"median_sharpe": 0.4, "median_crr": 0.08, "benchmark_crr": 0.02},
            "test": {"median_sharpe": -100.0},
        },
        {
            "symbol": "XAU/USD", "timeframe": "d1",
            "validation": {"median_sharpe": 0.2, "median_crr": 0.05, "benchmark_crr": 0.01},
            "test": {"median_sharpe": 100.0},
        },
    ]

    first = rank_markets(candidates)
    candidates[0]["test"]["median_sharpe"] = 1e9
    candidates[1]["test"]["median_sharpe"] = -1e9
    second = rank_markets(candidates)

    assert [(r["symbol"], r["timeframe"]) for r in first] == [
        (r["symbol"], r["timeframe"]) for r in second
    ] == [("EUR/USD", "h4"), ("XAU/USD", "d1")]


def test_no_hay_ganador_si_sharpe_no_es_positivo():
    from tradingbot.rl.selection import winner_key

    ranking = rank_markets([{
        "symbol": "EUR/USD",
        "timeframe": "h4",
        "validation": {"median_sharpe": -0.1, "median_crr": 0.08, "benchmark_crr": 0.02},
    }])

    assert ranking[0]["eligible"] is False
    assert ranking[0]["winner"] is False
    with pytest.raises(ValueError, match="ningún candidato"):
        winner_key(ranking)


# -- replay y referencia ---------------------------------------------------


def test_replay_produce_una_curva_de_equity_completa():
    ds = dataset_sintetico(100)
    agente = PPOAgent(ds.features.shape[1] + 3, PpoParams(hidden_sizes=(16, 16), seed=0))

    resultado = replay(agente, ds, EnvParams(max_units=10_000))

    assert len(resultado.equity) == len(ds)
    assert len(resultado.positions) == len(ds) - 1
    assert resultado.equity[0] == EnvParams().initial_equity
    assert np.isfinite(resultado.metrics.crr)


def test_buy_and_hold_replica_el_movimiento_del_precio():
    ds = dataset_sintetico(100)
    params = EnvParams(max_units=10_000, spread_pips=0.0)

    resultado = buy_and_hold(ds, params)

    esperado = (ds.prices[-1] - ds.prices[0]) * params.max_units
    assert resultado.equity[-1] - params.initial_equity == pytest.approx(esperado)
    assert resultado.trades == 1


def test_buy_and_hold_paga_el_spread_una_sola_vez():
    ds = dataset_sintetico(100)
    con_coste = buy_and_hold(ds, EnvParams(max_units=10_000, spread_pips=2.0))
    sin_coste = buy_and_hold(ds, EnvParams(max_units=10_000, spread_pips=0.0))

    diferencia = sin_coste.equity[-1] - con_coste.equity[-1]
    assert diferencia == pytest.approx(10_000 * 2.0 * 1e-4)


# -- registro --------------------------------------------------------------


def registro_de_prueba(run_id: str = "prueba-1") -> ModelRecord:
    return ModelRecord(
        run_id=run_id,
        created_at="2026-01-01T00:00:00+00:00",
        instrument="EUR/USD",
        timeframe="H1",
        train_range=["a", "b"],
        test_range=["c", "d"],
        fsr_params={},
        ppo_params={},
        env_params={},
        train_metrics={"crr": 0.1},
        test_metrics={"crr": 0.05},
    )


def test_el_registro_guarda_lista_y_recupera(tmp_path):
    reg = ModelRegistry(tmp_path)
    agente = PPOAgent(8, PpoParams(hidden_sizes=(16, 16)))

    reg.save(registro_de_prueba("run-a"), agente.state_dict())
    reg.save(registro_de_prueba("run-b"), agente.state_dict())

    ids = [r.run_id for r in reg.list()]
    assert set(ids) == {"run-a", "run-b"}
    assert reg.get("run-a").instrument == "EUR/USD"
    assert reg.get("no-existe") is None

    estado = reg.load_state("run-a")
    assert "policy" in estado and "value" in estado


def test_activar_un_modelo_cambia_el_puntero(tmp_path):
    reg = ModelRegistry(tmp_path)
    agente = PPOAgent(8, PpoParams(hidden_sizes=(16, 16)))
    reg.save(registro_de_prueba("run-a"), agente.state_dict())
    reg.save(registro_de_prueba("run-b"), agente.state_dict())

    assert reg.active_id() is None

    reg.activate("run-a")
    assert reg.active_id() == "run-a"
    reg.activate("run-b")
    assert reg.active().run_id == "run-b"

    reg.deactivate()
    assert reg.active() is None

    with pytest.raises(FileNotFoundError):
        reg.activate("inexistente")


def test_borrar_el_modelo_activo_limpia_el_puntero(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.save(registro_de_prueba("run-a"), PPOAgent(8, PpoParams(hidden_sizes=(16, 16))).state_dict())
    reg.activate("run-a")

    reg.delete("run-a")

    assert reg.active_id() is None
    assert reg.list() == []


def test_una_carpeta_corrupta_no_tumba_el_listado(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.save(registro_de_prueba("bueno"), PPOAgent(8, PpoParams(hidden_sizes=(16, 16))).state_dict())
    (tmp_path / "roto").mkdir()
    (tmp_path / "roto" / "meta.json").write_text("{ esto no es json")

    assert [r.run_id for r in reg.list()] == ["bueno"]


# -- entrenamiento completo ------------------------------------------------


def test_train_entrena_evalua_y_registra(tmp_path):
    """Ciclo completo en miniatura: entrenar, medir en test y dejarlo guardado."""
    ds = dataset_sintetico(300)
    entrena, evalua = ds.split(ds.timestamps[200])
    reg = ModelRegistry(tmp_path)

    ppo = PpoParams(hidden_sizes=(16, 16), iterations=2, episodes_per_iteration=2,
                    steps_per_episode=32, update_epochs=2, seed=0)

    resultado = train(entrena, evalua, ppo_params=ppo, registry=reg, timeframe="H1")

    assert len(resultado.history) == 2
    assert reg.get(resultado.record.run_id) is not None
    assert len(reg.history(resultado.record.run_id)) == 2

    # Los rangos guardados deben corresponder a los tramos usados.
    assert resultado.record.train_range[0] == str(entrena.timestamps[0])
    assert resultado.record.test_range[-1] == str(evalua.timestamps[-1])

    # Y las métricas de test deben venir del tramo de test, no del de train.
    assert resultado.test_replay.metrics.bars == len(evalua) - 1
    assert "crr" in resultado.record.test_metrics
    assert resultado.record.benchmark_metrics["strategy"] == "buy_and_hold"


def test_la_comparativa_no_publica_sharpe_de_curvas_no_comparables(tmp_path):
    """Las estrategias por regla solo registran equity al cerrar operación.

    Sobre esa curva a saltos la volatilidad no es comparable con la de FSRPPO,
    que se valora en cada barra: publicar su Sharpe al lado sería presentar como
    equivalentes dos cifras que no lo son.
    """
    from tradingbot.config import FsrParams
    from tradingbot.rl.dataset import build_dataset
    from tradingbot.rl.train import compare_with_benchmarks

    candles = velas(200)
    params = FsrParams(window=30, ensemble_size=3)
    ds = build_dataset(candles, params, cache_dir=tmp_path, workers=1)
    agente = PPOAgent(ds.features.shape[1] + 3, PpoParams(hidden_sizes=(16, 16), seed=0))

    filas = compare_with_benchmarks(agente, ds, candles, EnvParams(max_units=10_000))
    por_nombre = {f["name"]: f for f in filas}

    assert {"FSRPPO", "Buy & Hold", "bollinger", "rsi", "wyckoff_1"} <= set(por_nombre)

    for nombre in ("FSRPPO", "Buy & Hold"):
        assert por_nombre[nombre]["basis"] == "per_bar"
        assert por_nombre[nombre]["avr"] is not None

    for nombre in ("bollinger", "rsi", "wyckoff_1"):
        fila = por_nombre[nombre]
        if "error" in fila:
            continue
        assert fila["basis"] == "realised"
        assert fila["sharpe"] is None and fila["avr"] is None
        # Lo que sí es comparable se conserva.
        assert fila["crr"] is not None and fila["trades"] is not None
