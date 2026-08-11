from tradingbot.config import load_settings
from tradingbot.engine import BotEngine
from tradingbot.store import Store


def make_engine(tmp_path):
    store = Store(tmp_path / "test.db")
    return BotEngine(broker=None, store=store, settings=load_settings())


def test_update_settings_clamps_to_bounds(tmp_path):
    eng = make_engine(tmp_path)
    result = eng.update_settings(
        {"bb_period": 999, "risk_per_trade": 0.5, "bb_std": 0.1, "max_trades_per_day": 0}
    )
    assert result["bb_period"] == 50          # tope superior
    assert result["risk_per_trade"] == 0.02   # máx. 2%
    assert result["bb_std"] == 1.0            # mínimo
    assert result["max_trades_per_day"] == 1  # mínimo


def test_update_settings_ignores_unknown_and_invalid(tmp_path):
    eng = make_engine(tmp_path)
    before = eng.current_settings()
    result = eng.update_settings({"desconocido": 123, "bb_period": "no-numérico"})
    assert "desconocido" not in result
    assert result["bb_period"] == before["bb_period"]


def test_settings_persist_in_store(tmp_path):
    eng = make_engine(tmp_path)
    eng.update_settings({"bb_period": 30, "risk_per_trade": 0.01})
    sp = eng.strategy_params()
    rp = eng.risk_params()
    assert sp.bb_period == 30
    assert rp.risk_per_trade == 0.01
    # y sobrevive a un engine nuevo sobre el mismo store
    eng2 = BotEngine(broker=None, store=eng.store, settings=load_settings())
    assert eng2.strategy_params().bb_period == 30


def test_max_spread_bps_se_acota_como_el_resto_de_ajustes(tmp_path):
    eng = make_engine(tmp_path)
    assert eng.update_settings({"max_spread_bps": 999})["max_spread_bps"] == 100.0
    assert eng.update_settings({"max_spread_bps": 0.0})["max_spread_bps"] == 0.1
    assert eng.risk_params().max_spread_bps == 0.1


def test_spec_cae_en_eurusd_si_el_broker_no_la_expone(tmp_path):
    """Los brókers de papel y los dobles de test no tienen `spec`."""
    from tradingbot.config import DEFAULT_SPEC

    eng = make_engine(tmp_path)
    assert eng.spec() is DEFAULT_SPEC
    assert eng.symbol() == "EUR/USD"


class BrokerFalso:
    """Bróker mínimo para las rutas de orden manual."""

    connected = True

    def __init__(self, spec, lot_size):
        self.spec = spec
        self.instrument = spec.symbol
        self._lot_size = lot_size
        self.ordenes = []

    def normalize_units(self, units):
        return (units // self.spec.min_lot) * self.spec.min_lot

    def units_for_lots(self, lots):
        return self.normalize_units(int(round(lots * self._lot_size)))

    def open_position_pips(self, side, units, sl_pips, tp_pips):
        self.ordenes.append((side, units, sl_pips, tp_pips))
        return "orden-1"


def test_orden_manual_convierte_lotes_segun_la_clase_de_activo(tmp_path):
    from tradingbot.config import INSTRUMENT_SEEDS, InstrumentSpec

    eng = make_engine(tmp_path)
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["EUR/USD"], 100_000)
    assert eng.manual_order("long", 0.10, 10.0, 20.0)["units"] == 10_000
    # La etiqueta del log ya no es un literal EUR/USD.
    assert eng.symbol() == "EUR/USD"

    accion = InstrumentSpec("AAPL", pip=0.01, min_lot=1, typical_spread_pips=2.0,
                            asset_class="share", digits=2)
    eng2 = make_engine(tmp_path / "otro")
    eng2.broker = BrokerFalso(accion, 1)
    # 10 lotes de AAPL son 10 títulos, no 1.000.000.
    assert eng2.manual_order("long", 10, 1.0, 2.0)["units"] == 10


def test_policy_se_niega_a_operar_un_modelo_de_otro_instrumento(tmp_path, monkeypatch):
    """Defensa por si el mapa de activos y el meta.json discrepan.

    El registro indexa por instrumento, así que armar el modelo equivocado ya no
    debería poder pasar; si pasa (un active.json editado a mano, una carpeta
    renombrada), dimensionar con la ficha de un activo y ejecutar en otro sería
    silencioso. Por eso la comprobación sigue ahí.
    """
    import json

    from tradingbot.config import INSTRUMENT_SEEDS
    from tradingbot.rl import registry as registry_mod
    from tradingbot.rl.registry import ModelRegistry

    from test_model_registry import guarda

    modelos = tmp_path / "models"
    monkeypatch.setattr(registry_mod, "MODELS_DIR", modelos)
    reg = ModelRegistry(modelos)
    guarda(reg, "oro-1", "XAU/USD")
    # active.json editado a mano: apunta un modelo de oro bajo EUR/USD.
    reg.pointer_path.write_text(json.dumps({"EUR/USD": "oro-1"}))

    eng = make_engine(tmp_path)
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["EUR/USD"], 100_000)
    # Caché ya poblada: el meta del modelo dice oro, el bróker opera euros.
    eng._policy = object()
    eng._policy_key = ("EUR/USD", "oro-1")
    eng._policy_run_id = "oro-1"
    eng._policy_instrument = "XAU/USD"

    assert eng.policy() is None
    assert "XAU/USD" in eng.store.recent_logs()[-1]["message"]


def test_policy_cachea_por_instrumento_no_solo_por_modelo(tmp_path, monkeypatch):
    """Cambiar de símbolo invalida la política cacheada aunque no cambie el modelo."""
    from tradingbot.config import INSTRUMENT_SEEDS
    from tradingbot.rl import registry as registry_mod

    monkeypatch.setattr(registry_mod, "MODELS_DIR", tmp_path / "models")

    eng = make_engine(tmp_path)
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["XAU/USD"], 1)
    politica = object()
    eng._policy = politica
    eng._policy_key = ("XAU/USD", None)
    eng._policy_instrument = "XAU/USD"

    assert eng.policy() is politica
    # Mismo modelo activo (ninguno), otro instrumento: la caché no vale.
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["EUR/USD"], 100_000)
    assert eng.policy() is None


def test_status_refleja_el_modelo_del_instrumento_sin_esperar_a_una_vela(tmp_path, monkeypatch):
    """El panel pregunta justo tras cambiar de símbolo, antes de cualquier tick."""
    from tradingbot.config import INSTRUMENT_SEEDS
    from tradingbot.rl import registry as registry_mod
    from tradingbot.rl.registry import ModelRegistry

    from test_model_registry import guarda

    modelos = tmp_path / "models"
    monkeypatch.setattr(registry_mod, "MODELS_DIR", modelos)
    reg = ModelRegistry(modelos)
    guarda(reg, "euro-1", "EUR/USD")
    guarda(reg, "oro-1", "XAU/USD")
    reg.activate("euro-1")
    reg.activate("oro-1")

    eng = make_engine(tmp_path)
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["EUR/USD"], 100_000)
    assert eng.active_model_id() == "euro-1"
    assert eng.status()["active_model"] == "euro-1"

    # Cambio de instrumento: sin haber corrido ningún cierre de vela.
    eng.broker = BrokerFalso(INSTRUMENT_SEEDS["XAU/USD"], 1)
    estado = eng.status()
    assert estado["active_model"] == "oro-1"
    assert estado["active_model_instrument"] == "XAU/USD"
    assert estado["active_model_info"]["learning_rate"] == 0.0003


def test_model_instrument_tolera_un_registro_que_falla(tmp_path):
    class RegistroRoto:
        def get(self, _run_id):
            raise RuntimeError("registro ilegible")

    eng = make_engine(tmp_path)
    assert eng._model_instrument(RegistroRoto(), "run-1") is None
    assert eng._model_instrument(RegistroRoto(), None) is None
