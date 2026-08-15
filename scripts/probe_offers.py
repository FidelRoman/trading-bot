"""Sonda de SOLO LECTURA de la tabla OFFERS de FXCM.

Sirve para cerrar la unica incognita que no se puede resolver leyendo el wheel:
los valores numericos de ``instrument_type``. ForexConnect no expone el enum
O2GInstrumentType a Python, asi que el mapa de
``tradingbot.instruments._TYPE_CLASSES`` es provisional hasta ver esta salida.

Tambien verifica que ``point_size`` viene informado (de el sale el pip) y que
``get_base_unit_size`` responde para instrumentos de cada clase.

NO modifica nada: no envia ordenes ni cambia suscripciones.

Uso: uv run python scripts/probe_offers.py [Demo|Real]
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forexconnect import ForexConnect  # noqa: E402

from tradingbot.config import FxcmCredentials  # noqa: E402
from tradingbot.instruments import asset_class_of, pip_from_offer, symbol_of  # noqa: E402

COLUMNS = (
    "offer_id", "instrument", "instrument_type", "digits", "point_size",
    "pip_cost", "contract_multiplier", "contract_currency",
    "subscription_status", "trading_status", "bid", "ask",
)


def credentials(connection):
    """Credenciales de la conexion pedida, aceptando los dos esquemas de env."""
    suffix = connection.upper()
    user = os.getenv("FXCM_USER_{}".format(suffix)) or os.getenv("FXCM_USER", "")
    password = os.getenv("FXCM_PASS_{}".format(suffix)) or os.getenv("FXCM_PASS", "")
    creds = FxcmCredentials(
        user=user,
        password=password,
        connection=connection,
        url=os.getenv("FXCM_URL", "https://www.fxcorporate.com/Hosts.jsp"),
    )
    creds.validate()
    return creds


def cell(row, name):
    value = getattr(row, name, None)
    return "" if value is None else str(value)


def main():
    connection = sys.argv[1] if len(sys.argv) > 1 else "Demo"
    creds = credentials(connection)
    fx = ForexConnect()
    fx.login(creds.user, creds.password, creds.url, creds.connection, None, None,
             lambda session, status: None)
    try:
        rows = list(fx.get_table(ForexConnect.OFFERS))
        print("# ofertas en la tabla: {}".format(len(rows)))

        # La tabla del table-manager y el lector de login pueden diferir: si el
        # primero filtrase por suscripcion, el catalogo se quedaria corto.
        try:
            reader = list(fx.get_table_reader(ForexConnect.OFFERS))
            ids_tabla = set(cell(row, "offer_id") for row in rows)
            ids_reader = set(cell(row, "offer_id") for row in reader)
            print("# ofertas en el reader de login: {} (solo en tabla: {}, solo en reader: {})"
                  .format(len(reader), len(ids_tabla - ids_reader), len(ids_reader - ids_tabla)))
        except Exception as exc:
            print("# reader de login no disponible: {}".format(exc))

        print()
        print("\t".join(COLUMNS) + "\tclase_deducida\tpip_deducido")
        por_tipo = defaultdict(list)
        por_estado = defaultdict(int)
        for row in rows:
            clase = asset_class_of(row)
            valores = [cell(row, name) for name in COLUMNS]
            valores.append(clase)
            valores.append(str(pip_from_offer(row, clase)))
            print("\t".join(valores))
            por_tipo[cell(row, "instrument_type")].append(symbol_of(row))
            por_estado[cell(row, "subscription_status")] += 1

        print()
        print("== instrument_type -> cuantos y ejemplos (rellena _TYPE_CLASSES con esto)")
        for tipo in sorted(por_tipo, key=lambda value: (len(value), value)):
            simbolos = por_tipo[tipo]
            print("  tipo {!r}: {} instrumentos -> {}".format(
                tipo, len(simbolos), ", ".join(simbolos[:8])))

        print()
        print("== subscription_status -> cuantos ('T' es el unico operable)")
        for estado in sorted(por_estado):
            print("  {!r}: {}".format(estado, por_estado[estado]))

        print()
        print("== trading settings de una muestra por tipo")
        account = None
        for candidate in fx.get_table(ForexConnect.ACCOUNTS):
            account = candidate
            break
        provider = fx.login_rules.trading_settings_provider
        muestra = [simbolos[0] for simbolos in por_tipo.values() if simbolos]
        for symbol in muestra[:12]:
            datos = []
            for metodo in ("get_base_unit_size", "get_min_quantity",
                           "get_max_quantity", "get_market_status"):
                funcion = getattr(provider, metodo, None)
                if funcion is None:
                    datos.append("{}=n/d".format(metodo))
                    continue
                try:
                    datos.append("{}={}".format(metodo, funcion(symbol, account)))
                except Exception as exc:
                    datos.append("{}=ERROR({})".format(metodo, type(exc).__name__))
            print("  {}: {}".format(symbol, "  ".join(datos)))
    finally:
        fx.logout()


if __name__ == "__main__":
    main()
