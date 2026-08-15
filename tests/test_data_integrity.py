from pathlib import Path

from dotenv import dotenv_values
import pytest

from tradingbot.config import update_env_file
from tradingbot.web.training_job import TrainingJob


def test_update_env_file_es_atomico_privado_y_preserva_valores(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KEEP=uno\nFXCM_PASS=anterior\n")

    update_env_file({"FXCM_PASS": 'dos # con "comillas"'}, path)

    values = dotenv_values(path)
    assert values["KEEP"] == "uno"
    assert values["FXCM_PASS"] == 'dos # con "comillas"'
    assert path.stat().st_mode & 0o777 == 0o600


def test_update_env_file_rechaza_inyeccion_de_lineas(tmp_path):
    with pytest.raises(ValueError, match="saltos de línea"):
        update_env_file({"FXCM_PASS": "secreto\nOTRA=inyectada"}, tmp_path / ".env")


def test_dataset_de_entrenamiento_debe_coincidir_con_instrumento_y_timeframe(tmp_path, monkeypatch):
    history = tmp_path / "history"
    history.mkdir()
    good = history / "eurusd_h4_20240101_20250101.csv"
    good.write_text("time,open,high,low,close\n")
    monkeypatch.setattr("tradingbot.web.training_job.HISTORY_DIR", history)

    assert TrainingJob.validate_dataset(good.name, "EUR/USD", "h4") == good
    with pytest.raises(ValueError, match="no corresponde"):
        TrainingJob.validate_dataset(good.name, "XAU/USD", "h4")
    with pytest.raises(ValueError, match="no corresponde"):
        TrainingJob.validate_dataset(good.name, "EUR/USD", "d1")
