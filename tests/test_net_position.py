"""Ejecución de posición neta contra FXCM (la que usa FSRPPO).

Es el código que manda órdenes reales, así que se prueba cada transición con una
sesión ForexConnect falsa: ampliar, reducir con cierre parcial, dar la vuelta al
signo y aplanar. Sin sesión real ni credenciales.
"""
import pytest
from forexconnect import fxcorepy

from tradingbot.broker import FxcmBroker
from tradingbot.config import FxcmCredentials


class FakeTrade:
    def __init__(self, trade_id, amount, side, instrument="EUR/USD", open_rate=1.10):
        self.trade_id = trade_id
        self.amount = amount
        self.buy_sell = fxcorepy.Constants.BUY if side == "long" else fxcorepy.Constants.SELL
        self.instrument = instrument
        self.offer_id = "of-" + instrument
        self.open_rate = open_rate
        self.open_time = "2026-08-11T00:00:00"


class FakeOffer:
    def __init__(self, instrument="EUR/USD", bid=1.1000, ask=1.1002, digits=5):
        self.instrument = instrument
        self.offer_id = "of-" + instrument
        self.bid, self.ask, self.digits = bid, ask, digits
        self.subscription_status = "T"

    def is_digits_valid(self):
        return True

    def is_point_size_valid(self):
        return False

    def is_instrument_type_valid(self):
        return False


class FakeSession:
    """Sesión con tablas TRADES y OFFERS y registro de las órdenes enviadas."""

    def __init__(self, trades=(), instrument="EUR/USD"):
        self.trades = list(trades)
        self.offer = FakeOffer(instrument)
        self.sent = []

    def get_table(self, table):
        # El bróker pide OFFERS o TRADES; se distingue por lo que busca el llamador.
        if getattr(table, "name", str(table)).upper().find("OFFER") >= 0:
            return [self.offer]
        return list(self.trades)

    def create_order_request(self, **kwargs):
        return kwargs

    def send_request(self, request):
        self.sent.append(request)

        class Resp:
            order_id = "ord-%d" % len(self.sent)

        return Resp()


def make_broker(trades=(), instrument="EUR/USD", base_unit=1000, read_only=False):
    broker = FxcmBroker(FxcmCredentials(user="d", password="d"), instrument=instrument,
                        read_only=read_only)
    broker._fx = FakeSession(trades, instrument)
    broker._account_id = "acc-1"
    broker._base_unit_size = base_unit
    return broker


def _kinds(session):
    return [r.get("order_type") for r in session.sent]


OPEN = fxcorepy.Constants.Orders.TRUE_MARKET_OPEN
CLOSE = fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE


# -- lectura de la posición ----------------------------------------------------


def test_posicion_neta_agrega_largos_y_cortos():
    broker = make_broker([
        FakeTrade("1", 3000, "long"),
        FakeTrade("2", 1000, "short"),
    ])
    assert broker.position == 2000


def test_posicion_ignora_otros_instrumentos():
    broker = make_broker([
        FakeTrade("1", 3000, "long"),
        FakeTrade("2", 5000, "long", instrument="GBP/USD"),
    ])
    assert broker.position == 3000


def test_lecturas_de_posicion_sin_sesion_devuelven_plano():
    """La UI puede consultar mientras FXCM se desconecta, sin levantar 500."""
    broker = make_broker([FakeTrade("1", 3000, "long")])
    broker._fx = None

    assert broker.open_trades() == []
    assert broker.all_open_trades() == []
    assert broker.position == 0
    assert broker.entry_price == 0.0


def test_precio_medio_pondera_por_unidades():
    broker = make_broker([
        FakeTrade("1", 1000, "long", open_rate=1.10),
        FakeTrade("2", 3000, "long", open_rate=1.20),
    ])
    assert broker.entry_price == pytest.approx(1.175)


def test_precio_medio_es_cero_sin_posicion():
    assert make_broker().entry_price == 0.0


# -- transiciones --------------------------------------------------------------


def test_sin_cambio_no_manda_ordenes():
    broker = make_broker([FakeTrade("1", 2000, "long")])
    fill = broker.set_position(2000)
    assert fill["traded_units"] == 0
    assert broker._fx.sent == []


def test_abrir_desde_plano_compra_el_objetivo():
    broker = make_broker()
    fill = broker.set_position(3000)

    assert _kinds(broker._fx) == [OPEN]
    orden = broker._fx.sent[0]
    assert orden["BUY_SELL"] == fxcorepy.Constants.BUY
    assert orden["AMOUNT"] == 3000
    # La posición neta no lleva SL ni TP: la política decide la salida.
    assert "PEG_TYPE_STOP" not in orden and "RATE_LIMIT" not in orden
    assert fill["traded_units"] == 3000 and fill["position"] == 3000


def test_abrir_corto_desde_plano():
    broker = make_broker()
    broker.set_position(-2000)
    assert broker._fx.sent[0]["BUY_SELL"] == fxcorepy.Constants.SELL
    assert broker._fx.sent[0]["AMOUNT"] == 2000


def test_ampliar_solo_abre_el_delta():
    broker = make_broker([FakeTrade("1", 1000, "long")])
    broker.set_position(4000)

    assert _kinds(broker._fx) == [OPEN]
    assert broker._fx.sent[0]["AMOUNT"] == 3000       # no 4000
    assert broker._fx.sent[0]["BUY_SELL"] == fxcorepy.Constants.BUY


def test_reducir_cierra_parcialmente_un_solo_trade():
    broker = make_broker([FakeTrade("1", 5000, "long")])
    broker.set_position(2000)

    assert _kinds(broker._fx) == [CLOSE]
    orden = broker._fx.sent[0]
    assert orden["AMOUNT"] == 3000                     # cierre parcial
    assert orden["TRADE_ID"] == "1"
    assert orden["BUY_SELL"] == fxcorepy.Constants.SELL  # contrario a un largo


def test_reducir_recorre_varios_trades_y_parte_el_ultimo():
    broker = make_broker([
        FakeTrade("1", 2000, "long"),
        FakeTrade("2", 2000, "long"),
        FakeTrade("3", 2000, "long"),
    ])
    broker.set_position(1000)                          # hay que cerrar 5000

    cerrados = [(o["TRADE_ID"], o["AMOUNT"]) for o in broker._fx.sent]
    assert cerrados == [("1", 2000), ("2", 2000), ("3", 1000)]


def test_aplanar_cierra_todo_y_no_abre_nada():
    broker = make_broker([FakeTrade("1", 2000, "long"), FakeTrade("2", 1000, "long")])
    broker.set_position(0)

    assert _kinds(broker._fx) == [CLOSE, CLOSE]
    assert sum(o["AMOUNT"] for o in broker._fx.sent) == 3000


def test_dar_la_vuelta_cierra_todo_antes_de_abrir():
    broker = make_broker([FakeTrade("1", 2000, "long")])
    broker.set_position(-3000)

    # El orden importa: primero aplanar, luego abrir en sentido contrario.
    assert _kinds(broker._fx) == [CLOSE, OPEN]
    assert broker._fx.sent[0]["AMOUNT"] == 2000
    assert broker._fx.sent[1]["AMOUNT"] == 3000
    assert broker._fx.sent[1]["BUY_SELL"] == fxcorepy.Constants.SELL


def test_close_position_es_aplanar():
    broker = make_broker([FakeTrade("1", 1000, "long")])
    broker.close_position()
    assert _kinds(broker._fx) == [CLOSE]


# -- guardias ------------------------------------------------------------------


def test_objetivo_se_redondea_al_minimo_operable():
    broker = make_broker(base_unit=1000)
    broker.set_position(2500)
    # 2.500 no es múltiplo de 1.000: se opera 2.000, no se redondea hacia arriba.
    assert broker._fx.sent[0]["AMOUNT"] == 2000


def test_objetivo_por_debajo_del_minimo_no_abre_nada():
    broker = make_broker(base_unit=1000)
    fill = broker.set_position(500)
    assert broker._fx.sent == []
    assert fill["traded_units"] == 0


def test_read_only_bloquea_la_posicion_neta():
    broker = make_broker([FakeTrade("1", 1000, "long")], read_only=True)
    with pytest.raises(PermissionError, match="solo lectura"):
        broker.set_position(5000)
    assert broker._fx.sent == []


def test_el_signo_del_objetivo_se_respeta_tras_redondear():
    broker = make_broker(base_unit=1000)
    broker.set_position(-2500)
    assert broker._fx.sent[0]["BUY_SELL"] == fxcorepy.Constants.SELL
    assert broker._fx.sent[0]["AMOUNT"] == 2000
