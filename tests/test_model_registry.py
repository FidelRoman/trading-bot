"""El registro guarda un modelo activo por instrumento, no un puntero global.

Cada modelo lleva dentro la ficha del instrumento con el que se entrenó y con
ella se dimensionan las órdenes, así que el activo tiene que ser por símbolo:
cambiar de instrumento debe cambiar de modelo, no desarmar el bot.
"""
import json

import pytest

from tradingbot.rl.registry import ModelRecord, ModelRegistry


def registro_falso(run_id: str, instrument: str) -> ModelRecord:
    return ModelRecord(
        run_id=run_id,
        created_at="2026-08-09T22:33:15+00:00",
        instrument=instrument,
        timeframe="h1",
        train_range=["2024-07-10", "2026-01-08"],
        test_range=["2026-01-08", "2026-07-08"],
        fsr_params={"window": 50},
        ppo_params={"learning_rate": 0.0003},
        env_params={"spread_pips": 1.2},
        train_metrics={"crr": 0.06},
        test_metrics={"crr": -0.01},
    )


def guarda(reg: ModelRegistry, run_id: str, instrument: str) -> None:
    """Escribe el modelo sin pasar por torch: `activate` solo mira que exista."""
    destino = reg.path_for(run_id)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "meta.json").write_text(
        json.dumps(registro_falso(run_id, instrument).as_dict())
    )
    (destino / "model.pt").write_bytes(b"")


def test_dos_instrumentos_tienen_su_propio_activo(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")

    assert reg.activate("euro-1") == "EUR/USD"
    assert reg.activate("oro-1") == "XAU/USD"

    assert reg.active_id("EUR/USD") == "euro-1"
    assert reg.active_id("XAU/USD") == "oro-1"
    assert reg.active_map() == {"EUR/USD": "euro-1", "XAU/USD": "oro-1"}


def test_activar_sustituye_solo_dentro_del_mismo_instrumento(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "euro-2", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")
    reg.activate("euro-1")
    reg.activate("oro-1")

    reg.activate("euro-2")

    assert reg.active_id("EUR/USD") == "euro-2"
    assert reg.active_id("XAU/USD") == "oro-1"


def test_el_instrumento_lo_decide_el_modelo(tmp_path):
    """Activar no depende de la pantalla desde la que se pulsó."""
    reg = ModelRegistry(tmp_path)
    guarda(reg, "oro-1", "XAU/USD")

    assert reg.activate("oro-1") == "XAU/USD"
    assert reg.active_id("EUR/USD") is None


def test_desactivar_uno_no_toca_el_otro(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")
    reg.activate("euro-1")
    reg.activate("oro-1")

    reg.deactivate("EUR/USD")

    assert reg.active_id("EUR/USD") is None
    assert reg.active_id("XAU/USD") == "oro-1"

    reg.deactivate()
    assert reg.active_map() == {}


def test_borrar_limpia_solo_su_entrada(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")
    reg.activate("euro-1")
    reg.activate("oro-1")

    reg.delete("euro-1")

    assert reg.active_id("EUR/USD") is None
    assert reg.active_id("XAU/USD") == "oro-1"


def test_lee_el_formato_antiguo_de_puntero_unico(tmp_path):
    """Un active.json de la versión anterior no debe tumbar el arranque."""
    reg = ModelRegistry(tmp_path)
    guarda(reg, "oro-1", "XAU/USD")
    reg.pointer_path.write_text(json.dumps({"run_id": "oro-1"}))

    assert reg.active_map() == {"XAU/USD": "oro-1"}
    assert reg.active_id("XAU/USD") == "oro-1"
    assert reg.active_id("EUR/USD") is None


def test_formato_antiguo_apuntando_a_un_modelo_borrado(tmp_path):
    reg = ModelRegistry(tmp_path)
    reg.pointer_path.write_text(json.dumps({"run_id": "ya-no-existe"}))

    assert reg.active_map() == {}
    assert reg.active_id("EUR/USD") is None


def test_active_id_sin_instrumento_no_elige_por_su_cuenta(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")

    reg.activate("euro-1")
    assert reg.active_id() == "euro-1"      # con uno solo, no hay ambigüedad

    reg.activate("oro-1")
    assert reg.active_id() is None          # con dos, no hay respuesta correcta


def test_el_simbolo_se_normaliza_al_indexar(tmp_path):
    reg = ModelRegistry(tmp_path)
    guarda(reg, "euro-1", "EUR/USD")
    reg.activate("euro-1")

    assert reg.active_id("eurusd") == "euro-1"


def test_activar_un_modelo_sin_meta_falla(tmp_path):
    reg = ModelRegistry(tmp_path)
    (tmp_path / "huerfano").mkdir()
    (tmp_path / "huerfano" / "model.pt").write_bytes(b"")

    with pytest.raises(FileNotFoundError):
        reg.activate("huerfano")
