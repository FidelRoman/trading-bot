"""Activa la suscripción de un instrumento en la cuenta FXCM (estado "T").

Las cuentas demo suelen traer la mayoría de instrumentos en estado "D"
(deshabilitado) o "V" (solo ver); para operar via API deben estar en "T".
El cambio persiste en la cuenta entre sesiones.

Uso: uv run python scripts/subscribe_instrument.py [EUR/USD]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forexconnect import Common, ForexConnect, fxcorepy

from tradingbot.config import load_settings


def main() -> None:
    instrument = sys.argv[1] if len(sys.argv) > 1 else "EUR/USD"
    s = load_settings()
    s.fxcm.validate()
    fx = ForexConnect()
    fx.login(s.fxcm.user, s.fxcm.password, s.fxcm.url, s.fxcm.connection, None, None,
             lambda sess, st: None)
    try:
        target = None
        for o in fx.get_table(ForexConnect.OFFERS):
            if o.instrument == instrument:
                target = o
                break
        if target is None:
            raise SystemExit(f"{instrument} no existe en la tabla de ofertas")
        print(f"{instrument}: estado actual '{target.subscription_status}'")
        if target.subscription_status == "T":
            print("Ya está suscrito para operar ✅")
            return
        request = fx.create_request({
            fxcorepy.O2GRequestParamsEnum.COMMAND:
                fxcorepy.Constants.Commands.SET_SUBSCRIPTION_STATUS,
            fxcorepy.O2GRequestParamsEnum.OFFER_ID: target.offer_id,
            fxcorepy.O2GRequestParamsEnum.SUBSCRIPTION_STATUS: "T",
        })
        fx.send_request(request)
        time.sleep(2)
        offer = Common.get_offer(fx, instrument)
        status = offer.subscription_status if offer else "?"
        print(f"{instrument}: nuevo estado '{status}' " + ("✅" if status == "T" else "⚠️"))
    finally:
        fx.logout()


if __name__ == "__main__":
    main()
