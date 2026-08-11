"""Descubrimiento del universo de instrumentos operables de la cuenta FXCM.

Vercel no tiene credenciales FXCM, así que el catálogo lo construye el worker
(``scripts/scheduled_tick.py``) recorriendo la tabla OFFERS y lo publica como un
único documento de estado en Firestore. Va en un documento y no en una colección
porque el cliente REST de la UI (``web-ui/lib/server/firestore.ts``) pagina de
1.000 en 1.000 sin soportar queries: una colección por oferta costaría cientos de
lecturas por carga de página.

Este módulo **no importa forexconnect a propósito**. Opera por duck typing sobre
filas "row-like" para poder testearse con dobles en cualquier plataforma, ya que
``broker.py`` sí importa el wheel a nivel de módulo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .config import CURRENCY_CODES, INSTRUMENT_SEEDS, InstrumentSpec

FOREX = "forex"
INDEX = "index"
COMMODITY = "commodity"
TREASURY = "treasury"
BULLION = "bullion"
SHARE = "share"
CRYPTO = "crypto"
OTHER = "other"

#: Orden en que la UI agrupa los ``<optgroup>``.
ASSET_CLASSES = (FOREX, INDEX, COMMODITY, BULLION, TREASURY, CRYPTO, SHARE, OTHER)

# Valores del enum O2GInstrumentType de ForexConnect. PROVISIONAL: no están
# documentados en el wheel y no se pueden deducir del repo, así que
# scripts/probe_offers.py los verifica contra la cuenta real. Cualquier valor no
# mapeado cae en la heurística por símbolo de _class_from_symbol().
_TYPE_CLASSES = {
    1: FOREX,
    2: INDEX,
    3: COMMODITY,
    4: TREASURY,
    5: BULLION,
    6: SHARE,
    7: FOREX,     # FX index / basket
    8: CRYPTO,
}

_METALS = frozenset(("XAU", "XAG", "XPT", "XPD"))

_CRYPTOS = frozenset(("BTC", "ETH", "LTC", "XRP", "BCH", "ADA", "SOL", "DOT"))

# Materias primas de FXCM, que no llevan barra ni dígitos y por forma pasarían
# por acciones: USOil, UKOil, NGAS, Copper, WHEAT, SOYBN...
_COMMODITY_HINTS = ("OIL", "NGAS", "GAS", "COPPER", "WHEAT", "SOYB", "CORN", "SUGAR")

# Índices de FXCM sin dígitos en el nombre.
_INDEX_HINTS = ("BUND", "VOLX", "ESP35", "CHN", "HKG")

#: Unidades por lote estándar en FX. Fuera de divisas el lote es el propio
#: base_unit_size del bróker (1 acción, 1 contrato de índice…).
FOREX_LOT_SIZE = 100_000


def _attr(row: Any, *names: str, **kwargs: Any) -> Any:
    """Primer atributo no nulo de ``row`` entre ``names``.

    ForexConnect expone las columnas con nombres distintos según versión (snake
    case en el binding de Python, CamelCase en algunos builds), de ahí la lista.
    """
    default = kwargs.get("default")
    for name in names:
        value = getattr(row, name, None)
        if value is not None and value != "":
            return value
    return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def symbol_of(row: Any) -> str:
    return str(_attr(row, "instrument", "Instrument", default="")).strip().upper()


def _class_from_symbol(symbol: str) -> str:
    """Clase de activo deducida del símbolo, cuando el bróker no la declara.

    Último recurso, solo si ``instrument_type`` no viene o es un valor que
    ``_TYPE_CLASSES`` no conoce. Ante la duda devuelve ``share``/``other``, nunca
    ``forex``: esa clase habilita el lote de 100.000 unidades.
    """
    if "/" in symbol:
        base, _, quote = symbol.partition("/")
        if base in _METALS:
            return BULLION
        if base in _CRYPTOS or quote in _CRYPTOS:
            return CRYPTO
        if base in CURRENCY_CODES and quote in CURRENCY_CODES:
            return FOREX
        return OTHER
    if symbol in _CRYPTOS:
        return CRYPTO
    if any(hint in symbol for hint in _COMMODITY_HINTS):
        return COMMODITY
    if any(hint in symbol for hint in _INDEX_HINTS):
        return INDEX
    # Los índices de FXCM llevan el número en el nombre (US30, GER30, NAS100,
    # UK100, JPN225); las acciones son tickers alfabéticos.
    if any(char.isdigit() for char in symbol):
        return INDEX
    return SHARE


def asset_class_of(row: Any) -> str:
    """Clase de activo de una oferta: ``instrument_type`` y, si no, el símbolo.

    Nunca devuelve ``forex`` por defecto: es la clase que habilita la convención
    de lote de 100.000 unidades, así que adivinarla mal sobredimensionaría las
    órdenes ×100.000. Lo desconocido cae en la heurística del símbolo.
    """
    if _valid(row, "is_instrument_type_valid"):
        declared = _TYPE_CLASSES.get(_to_int(_attr(row, "instrument_type", "InstrumentType"), -1))
        if declared is not None:
            return declared
    return _class_from_symbol(symbol_of(row))


def _valid(row: Any, predicate: str) -> bool:
    """¿La oferta declara válida esa columna?

    ForexConnect expone ``is_<columna>_valid()`` en O2GOfferRow; leer una columna
    inválida devuelve basura. Si el predicado no existe (dobles de test), se
    asume válida.
    """
    check = getattr(row, predicate, None)
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:
        return False


def pip_from_offer(row: Any, asset_class: Optional[str] = None) -> float:
    """Tamaño de pip de una oferta.

    ``point_size`` es la fuente autoritativa: en ForexConnect es el tamaño de pip
    y el dígito extra de las cotizaciones fraccionarias va aparte, en
    ``fractional_pip_size``. Solo si el bróker no lo declara válido se cae a
    ``digits``, y ahí la regla depende de la clase de activo: en divisas el pip es
    la penúltima cifra (EUR/USD 5 dígitos → 0,0001; USD/JPY 3 → 0,01) y fuera de
    divisas la última (XAU/USD 2 dígitos → 0,01). Esa regla condicionada es la
    única que reproduce las cuatro especificaciones de ``INSTRUMENT_SEEDS``.
    """
    if _valid(row, "is_point_size_valid"):
        point = _to_float(_attr(row, "point_size", "PointSize"))
        if point > 0:
            return point
    if asset_class is None:
        asset_class = asset_class_of(row)
    if _valid(row, "is_digits_valid"):
        digits = _to_int(_attr(row, "digits", "Digits"), 0)
        if digits > 0:
            exponent = digits - 1 if asset_class == FOREX else digits
            return round(10.0 ** -exponent, 10)
    return INSTRUMENT_SEEDS["EUR/USD"].pip


def lot_size_for(asset_class: str, base_unit_size: int) -> int:
    """Unidades que equivalen a 1 lote para esa clase de activo.

    En divisas el mercado usa el lote estándar de 100.000 unidades. Fuera de
    divisas ``lots * 100_000`` no significa nada (1 lote de una acción no son
    100.000 títulos), así que el lote es el propio tamaño base del bróker.
    """
    if asset_class == FOREX:
        return FOREX_LOT_SIZE
    return max(int(base_unit_size), 1)


def offer_to_entry(row: Any, base_unit_size: int = 1) -> Optional[dict]:
    """Entrada compacta de catálogo a partir de una fila de la tabla OFFERS.

    ``base_unit_size`` viene de
    ``fx.login_rules.trading_settings_provider.get_base_unit_size()``, la fuente
    autoritativa del mínimo operable (el mismo dato que ya cachea
    ``FxcmBroker.connect``). Devuelve ``None`` si la fila no tiene símbolo.
    """
    symbol = symbol_of(row)
    if not symbol:
        return None
    asset_class = asset_class_of(row)
    pip = pip_from_offer(row, asset_class)
    bid = _to_float(_attr(row, "bid", "Bid"))
    ask = _to_float(_attr(row, "ask", "Ask"))
    min_lot = max(_to_int(base_unit_size, 1), 1)
    entry = {
        "symbol": symbol,
        "offer_id": str(_attr(row, "offer_id", "OfferID", default="")),
        "asset_class": asset_class,
        "digits": _to_int(_attr(row, "digits", "Digits"), 5),
        "pip": pip,
        "min_lot": min_lot,
        "lot_size": lot_size_for(asset_class, min_lot),
        "quote_currency": _quote_currency(row, symbol),
        "subscription_status": str(_attr(row, "subscription_status", "SubscriptionStatus",
                                         default="")).strip().upper() or "?",
        "tradable": False,
        "bid": bid,
        "ask": ask,
        # Diagnóstico: permite a scripts/probe_offers.py validar la derivación de
        # pip sin tener que volver a conectarse.
        "point_size": _to_float(_attr(row, "point_size", "PointSize")),
        "pip_cost": _to_float(_attr(row, "pip_cost", "PipCost")),
    }
    entry["tradable"] = entry["subscription_status"] == "T"
    if pip > 0 and ask > bid > 0:
        entry["typical_spread_pips"] = round((ask - bid) / pip, 2)
    else:
        entry["typical_spread_pips"] = 0.0
    return entry


def _quote_currency(row: Any, symbol: str) -> str:
    declared = _attr(row, "contract_currency", "ContractCurrency")
    if declared:
        return str(declared).strip().upper()
    if "/" in symbol:
        return symbol.partition("/")[2]
    return "USD"


#: Campos que cambian en cada tick con el precio. Quedan fuera de la huella para
#: que el catálogo no se reescriba 288 veces al día (cuota Firestore gratuita:
#: 20.000 escrituras/día).
_VOLATILE_FIELDS = ("bid", "ask", "typical_spread_pips")


def catalog_hash(entries: list) -> str:
    """Huella del contenido estructural del catálogo.

    Ignora precios: solo cambia si aparecen o desaparecen instrumentos, o si
    cambia su estado de suscripción, pip o mínimo operable.
    """
    import hashlib
    import json

    estable = [
        {key: value for key, value in entry.items() if key not in _VOLATILE_FIELDS}
        for entry in entries
    ]
    payload = json.dumps(estable, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def should_publish(previous: Optional[dict], catalog: dict,
                   max_age_hours: float = 24.0) -> bool:
    """¿Merece la pena escribir el catálogo en Firestore?

    Solo si cambió su contenido estructural, si cambió de cuenta, o si el
    publicado ya es viejo. Sin esta puerta el worker gastaría toda la cuota diaria
    de escrituras reescribiendo la misma lista cada cinco minutos.
    """
    if not previous:
        return True
    if previous.get("hash") != catalog.get("hash"):
        return True
    if previous.get("connection") != catalog.get("connection"):
        return True
    anterior = previous.get("updated_at")
    if not anterior:
        return True
    try:
        publicado = datetime.fromisoformat(str(anterior))
    except ValueError:
        return True
    if publicado.tzinfo is None:
        publicado = publicado.replace(tzinfo=timezone.utc)
    edad = (datetime.now(timezone.utc) - publicado).total_seconds()
    return edad >= max_age_hours * 3600.0


def build_catalog(rows: Iterable[Any], connection: str,
                  base_unit_sizes: Optional[dict] = None,
                  max_entries: int = 1500) -> dict:
    """Documento de catálogo listo para ``store.set_state('instrument_catalog')``.

    Los operables (``subscription_status == 'T'``) van primero para que el
    truncado, si ocurre, no se coma justo lo que el usuario puede usar. El límite
    de un documento Firestore es 1 MiB y la tabla OFFERS de una cuenta completa
    ronda las 2.000 filas, así que el corte se marca de forma explícita en
    ``truncated`` en vez de perder entradas en silencio.
    """
    sizes = base_unit_sizes or {}
    entries = []
    for row in rows:
        entry = offer_to_entry(row, sizes.get(symbol_of(row), 1))
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: (
        not item["tradable"],
        ASSET_CLASSES.index(item["asset_class"]) if item["asset_class"] in ASSET_CLASSES
        else len(ASSET_CLASSES),
        item["symbol"],
    ))
    total = len(entries)
    visibles = entries[:max_entries]
    clases: dict = {}
    for entry in visibles:
        clases[entry["asset_class"]] = clases.get(entry["asset_class"], 0) + 1
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "connection": connection,
        "count": len(visibles),
        "total": total,
        "truncated": total > max_entries,
        "tradable": sum(1 for entry in visibles if entry["tradable"]),
        "classes": clases,
        "hash": catalog_hash(visibles),
        "instruments": visibles,
    }


def spec_from_entry(entry: dict) -> InstrumentSpec:
    """``InstrumentSpec`` a partir de una entrada de catálogo."""
    return InstrumentSpec(
        symbol=str(entry["symbol"]),
        pip=float(entry["pip"]),
        min_lot=max(int(entry.get("min_lot", 1)), 1),
        typical_spread_pips=max(float(entry.get("typical_spread_pips", 0.0)), 0.0),
        quote_currency=str(entry.get("quote_currency", "USD")),
        asset_class=str(entry.get("asset_class", FOREX)),
        digits=max(int(entry.get("digits", 5)), 0),
    )


def find_entry(catalog: Optional[dict], symbol: str) -> Optional[dict]:
    """Entrada del catálogo para ``symbol``, o ``None``.

    Normaliza igual que ``config.get_instrument_spec``, así que acepta tanto
    ``eurusd`` como ``EUR/USD``.
    """
    if not catalog:
        return None
    from .config import normalize_symbol

    wanted = normalize_symbol(symbol)
    for entry in catalog.get("instruments") or ():
        if str(entry.get("symbol", "")).upper() == wanted:
            return entry
    return None
