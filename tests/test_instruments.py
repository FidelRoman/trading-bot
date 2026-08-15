"""Descubrimiento del catálogo de instrumentos y derivación de sus contratos.

Los dobles imitan una fila de la tabla OFFERS de ForexConnect, incluidos los
predicados ``is_<columna>_valid()``, para que estas pruebas no necesiten sesión
FXCM ni el wheel de Linux.
"""
import pytest

from tradingbot.config import (
    INSTRUMENT_SEEDS,
    get_instrument_spec,
    normalize_symbol,
)
from tradingbot.instruments import (
    asset_class_of,
    build_catalog,
    catalog_hash,
    find_entry,
    lot_size_for,
    offer_to_entry,
    pip_from_offer,
    should_publish,
    spec_from_entry,
)


class FakeOffer:
    """Fila de OFFERS con las columnas que expone O2GOfferRow."""

    def __init__(self, instrument, digits=5, point_size=None, instrument_type=None,
                 subscription_status="T", bid=1.0800, ask=1.0802,
                 contract_currency=None, offer_id="1"):
        self.instrument = instrument
        self.digits = digits
        self.point_size = point_size
        self.instrument_type = instrument_type
        self.subscription_status = subscription_status
        self.bid = bid
        self.ask = ask
        self.contract_currency = contract_currency
        self.offer_id = offer_id

    def is_digits_valid(self):
        return self.digits is not None

    def is_point_size_valid(self):
        return self.point_size is not None

    def is_instrument_type_valid(self):
        return self.instrument_type is not None


# -- normalización de símbolos -------------------------------------------------


@pytest.mark.parametrize("entrada,esperado", [
    ("eurusd", "EUR/USD"),
    ("EUR/USD", "EUR/USD"),
    ("xauusd", "XAU/USD"),
    ("  usdjpy  ", "USD/JPY"),
    # Los tickers que no son pares de divisas pasan intactos: partirlos era
    # justo lo que impedía operar acciones, índices y CFD.
    ("AAPL", "AAPL"),
    ("US30", "US30"),
    ("NAS100", "NAS100"),
    ("usoil", "USOIL"),
    # Seis letras que no son dos códigos de divisa no llevan barra.
    ("AAPLUS", "AAPLUS"),
    ("SOYBN", "SOYBN"),
])
def test_normalize_symbol_no_impone_forma_de_par(entrada, esperado):
    assert normalize_symbol(entrada) == esperado


def test_get_instrument_spec_acepta_cualquier_simbolo_del_catalogo():
    catalog = build_catalog([FakeOffer("US30", digits=1, instrument_type=2)], "Demo")
    spec = get_instrument_spec("US30", catalog)
    assert spec.symbol == "US30"
    assert spec.asset_class == "index"
    # Sin catálogo solo resuelven las semillas, y el error dice qué hay.
    with pytest.raises(ValueError, match="instrumento desconocido"):
        get_instrument_spec("US30")


def test_get_instrument_spec_sigue_resolviendo_las_semillas():
    for symbol, spec in INSTRUMENT_SEEDS.items():
        assert get_instrument_spec(symbol) is spec


# -- derivación del pip --------------------------------------------------------


def test_point_size_manda_sobre_digits():
    """``point_size`` es el pip real; ``fractional_pip_size`` va aparte."""
    offer = FakeOffer("EUR/USD", digits=5, point_size=0.0001)
    assert pip_from_offer(offer) == 0.0001


@pytest.mark.parametrize("symbol,digits,esperado", [
    ("EUR/USD", 5, 0.0001),
    ("GBP/USD", 5, 0.0001),
    ("USD/JPY", 3, 0.01),
    ("XAU/USD", 2, 0.01),
])
def test_pip_por_digits_reproduce_las_semillas(symbol, digits, esperado):
    """Sin ``point_size``, la regla por dígitos debe dar el pip ya validado.

    En divisas el pip es la penúltima cifra y fuera de divisas la última: es la
    única regla que cuadra con las cuatro especificaciones semilla.
    """
    assert pip_from_offer(FakeOffer(symbol, digits=digits)) == esperado
    assert pip_from_offer(FakeOffer(symbol, digits=digits)) == INSTRUMENT_SEEDS[symbol].pip


def test_pip_de_ultimo_recurso_es_el_de_eurusd():
    assert pip_from_offer(FakeOffer("RARO", digits=None)) == INSTRUMENT_SEEDS["EUR/USD"].pip


# -- clase de activo -----------------------------------------------------------


@pytest.mark.parametrize("tipo,esperado", [
    (1, "forex"), (2, "index"), (3, "commodity"),
    (4, "treasury"), (5, "bullion"), (6, "share"), (8, "crypto"),
])
def test_instrument_type_declarado_manda(tipo, esperado):
    assert asset_class_of(FakeOffer("CUALQUIERA", instrument_type=tipo)) == esperado


@pytest.mark.parametrize("symbol,esperado", [
    ("EUR/USD", "forex"),
    ("XAU/USD", "bullion"),
    ("BTC/USD", "crypto"),
    ("US30", "index"),
    ("NAS100", "index"),
    ("USOIL", "commodity"),
    ("AAPL", "share"),
])
def test_heuristica_por_simbolo_cuando_no_hay_tipo(symbol, esperado):
    assert asset_class_of(FakeOffer(symbol)) == esperado


def test_tipo_desconocido_nunca_cae_en_forex():
    """``forex`` habilita el lote de 100.000: adivinarlo mal multiplica ×100.000."""
    assert asset_class_of(FakeOffer("AAPL", instrument_type=99)) == "share"


# -- lotes ---------------------------------------------------------------------


def test_lote_es_100k_solo_en_divisas():
    assert lot_size_for("forex", 1_000) == 100_000
    # 1 lote de una acción no son 100.000 títulos.
    assert lot_size_for("share", 1) == 1
    assert lot_size_for("bullion", 1) == 1


# -- entradas y catálogo -------------------------------------------------------


def test_offer_to_entry_calcula_spread_y_operabilidad():
    offer = FakeOffer("EUR/USD", digits=5, point_size=0.0001, bid=1.0800, ask=1.0802)
    entry = offer_to_entry(offer, base_unit_size=1_000)
    assert entry["symbol"] == "EUR/USD"
    assert entry["pip"] == 0.0001
    assert entry["min_lot"] == 1_000
    assert entry["lot_size"] == 100_000
    assert entry["typical_spread_pips"] == 2.0
    assert entry["tradable"] is True


def test_catalogo_conserva_el_multiplicador_de_contrato():
    offer = FakeOffer("US30")
    offer.contract_multiplier = 10
    entry = offer_to_entry(offer, base_unit_size=1)

    assert entry["contract_multiplier"] == 10
    assert spec_from_entry(entry).contract_multiplier == 10


def test_offer_to_entry_marca_no_operable_lo_que_no_este_en_T():
    for estado in ("D", "V"):
        entry = offer_to_entry(FakeOffer("AAPL", subscription_status=estado))
        assert entry["subscription_status"] == estado
        assert entry["tradable"] is False


def test_offer_sin_simbolo_se_descarta():
    assert offer_to_entry(FakeOffer("")) is None


def test_catalogo_pone_primero_lo_operable():
    rows = [
        FakeOffer("AAPL", subscription_status="D", offer_id="1"),
        FakeOffer("EUR/USD", subscription_status="T", offer_id="2"),
        FakeOffer("US30", subscription_status="V", offer_id="3"),
    ]
    catalog = build_catalog(rows, "Demo")
    # Si el truncado recorta, no debe comerse justo lo que se puede operar.
    assert catalog["instruments"][0]["symbol"] == "EUR/USD"
    assert catalog["tradable"] == 1
    assert catalog["count"] == 3
    assert catalog["truncated"] is False


def test_catalogo_marca_el_truncado_en_vez_de_perder_entradas():
    rows = [FakeOffer("SYM{}".format(i), offer_id=str(i)) for i in range(10)]
    catalog = build_catalog(rows, "Demo", max_entries=4)
    assert catalog["truncated"] is True
    assert catalog["count"] == 4
    assert catalog["total"] == 10


def test_find_entry_y_spec_from_entry():
    catalog = build_catalog([FakeOffer("USD/JPY", digits=3, instrument_type=1,
                                       bid=150.00, ask=150.02)], "Demo")
    entry = find_entry(catalog, "usdjpy")
    assert entry is not None
    spec = spec_from_entry(entry)
    assert spec.pip == 0.01
    assert spec.asset_class == "forex"
    assert spec.lot_size == 100_000
    assert find_entry(catalog, "NO/EXISTE") is None


# -- puerta de escritura -------------------------------------------------------


def test_la_huella_ignora_los_precios():
    """Sin esto el worker reescribiría el catálogo en cada uno de los 288 ticks."""
    barato = build_catalog([FakeOffer("EUR/USD", bid=1.0800, ask=1.0802)], "Demo")
    caro = build_catalog([FakeOffer("EUR/USD", bid=1.0900, ask=1.0930)], "Demo")
    assert barato["hash"] == caro["hash"]
    assert should_publish(barato, caro) is False


def test_se_publica_si_cambia_la_suscripcion_o_el_universo():
    previo = build_catalog([FakeOffer("EUR/USD", subscription_status="T")], "Demo")
    suscrito = build_catalog([FakeOffer("EUR/USD", subscription_status="D")], "Demo")
    assert should_publish(previo, suscrito) is True

    nuevo = build_catalog(
        [FakeOffer("EUR/USD", offer_id="1"), FakeOffer("AAPL", offer_id="2")], "Demo")
    assert should_publish(previo, nuevo) is True


def test_se_publica_sin_catalogo_previo_o_al_cambiar_de_cuenta():
    catalog = build_catalog([FakeOffer("EUR/USD")], "Demo")
    assert should_publish(None, catalog) is True
    assert should_publish({}, catalog) is True
    assert should_publish(build_catalog([FakeOffer("EUR/USD")], "Real"), catalog) is True


def test_se_republica_cuando_el_publicado_es_viejo():
    catalog = build_catalog([FakeOffer("EUR/USD")], "Demo")
    viejo = dict(catalog, updated_at="2020-01-01T00:00:00+00:00")
    assert should_publish(viejo, catalog) is True
    # Una fecha corrupta no debe dejar el catálogo congelado para siempre.
    assert should_publish(dict(catalog, updated_at="no-es-fecha"), catalog) is True


def test_catalog_hash_es_estable_e_independiente_del_orden_de_claves():
    entries = build_catalog([FakeOffer("EUR/USD")], "Demo")["instruments"]
    revueltas = [dict(reversed(list(entry.items()))) for entry in entries]
    assert catalog_hash(entries) == catalog_hash(revueltas)
