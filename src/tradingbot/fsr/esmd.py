"""ESMD — Extreme-point Symmetric Mode Decomposition (Algoritmo 2 del paper).

Wang & Wang (2024), *Eng. Appl. of AI* 138, 109365, apéndice; método original de
Wang & Li (2013).

La idea: en vez de envolventes sobre los extremos (como EMD), ESMD interpola los
**puntos medios** de los segmentos que unen extremos adyacentes. Construye ``C``
splines cúbicos distintos sobre subconjuntos alternos de esos puntos medios,
promedia (la curva ``CSI``) y la resta. Al repetirlo hasta que ``max|CSI| ≤ δ``
queda una función de modo intrínseco (IMF).

Dos precisiones respecto al pseudocódigo publicado:

* El Algoritmo 2 escribe ``IMF_i = CSI``, pero el bucle interno solo termina
  cuando ``max|CSI| ≤ δ``, es decir cuando ``CSI ≈ 0``. La IMF es la señal
  tamizada ``Y`` (y por eso el residuo se define como ``L_i = X − IMF_i``).
  Implementamos ``IMF_i = Y``.
* ``δ = 0.001`` es un umbral **absoluto** pensado para precios de acciones chinas
  (decenas de yuanes). En EUR/USD, donde el rango de una ventana son milésimas,
  ese umbral pararía el tamizado en la primera pasada. Por defecto interpretamos
  δ como fracción del rango de la señal (``delta_mode="range"``), que es
  invariante de escala y equivale al valor del paper en su dominio original.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import solve_banded

__all__ = [
    "find_extrema",
    "mean_curve",
    "sift",
    "esmd",
    "delta_threshold",
    "cubic_spline_on_grid",
]


def cubic_spline_on_grid(x: np.ndarray, y: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Spline cúbico *not-a-knot* evaluado en ``grid``. Requiere ``len(x) >= 4``.

    Equivale a ``CubicSpline(x, y)(grid)`` de scipy, pero sin construir el
    objeto. El tamizado llama a esto ~22.000 veces por ventana sobre nodos de
    unos 25 puntos, y en ese régimen la validación y el andamiaje de
    ``CubicSpline`` costaban el 71 % del tiempo total de FSR: más que resolver
    el sistema. Aquí se monta el sistema tridiagonal y se resuelve directamente.

    La equivalencia con scipy está fijada en
    ``tests/test_fsr.py::test_el_spline_propio_coincide_con_scipy``.
    """
    dx = np.diff(x)
    slope = np.diff(y) / dx
    n = x.size

    # Sistema tridiagonal en las derivadas primeras k_i (misma formulación que
    # scipy.interpolate.CubicSpline), en formato de banda para solve_banded.
    ab = np.zeros((3, n))
    rhs = np.empty(n)

    ab[1, 1:-1] = 2 * (dx[:-1] + dx[1:])
    ab[0, 2:] = dx[:-1]
    ab[2, :-2] = dx[1:]
    rhs[1:-1] = 3 * (dx[1:] * slope[:-1] + dx[:-1] * slope[1:])

    # Contorno not-a-knot: continuidad de la tercera derivada en x[1] y x[-2].
    izquierda = x[2] - x[0]
    ab[1, 0] = dx[1]
    ab[0, 1] = izquierda
    rhs[0] = (
        (dx[0] + 2 * izquierda) * dx[1] * slope[0] + dx[0] ** 2 * slope[1]
    ) / izquierda

    derecha = x[-1] - x[-3]
    ab[1, -1] = dx[-2]
    ab[2, -2] = derecha
    rhs[-1] = (
        dx[-1] ** 2 * slope[-2] + (2 * derecha + dx[-1]) * dx[-2] * slope[-1]
    ) / derecha

    k = solve_banded((1, 1), ab, rhs, overwrite_ab=True, overwrite_b=True,
                     check_finite=False)

    # Coeficientes por tramo y evaluación en la rejilla.
    t = (k[:-1] + k[1:] - 2 * slope) / dx
    c3 = t / dx
    c2 = (slope - k[:-1]) / dx - t
    c1 = k[:-1]
    c0 = y[:-1]

    tramo = np.clip(np.searchsorted(x, grid, side="right") - 1, 0, n - 2)
    s = grid - x[tramo]
    return ((c3[tramo] * s + c2[tramo]) * s + c1[tramo]) * s + c0[tramo]


def find_extrema(x: np.ndarray) -> np.ndarray:
    """Índices de los máximos y mínimos locales de ``x``.

    Una meseta de puntos adyacentes iguales cuenta como un solo extremo (así lo
    exige la condición (1) de §2.1.1) y se le asigna su índice central.
    """
    x = np.asarray(x, dtype=float)
    if x.size < 3:
        return np.empty(0, dtype=int)

    signs = np.sign(np.diff(x))
    nonzero = np.flatnonzero(signs)
    if nonzero.size < 2:
        return np.empty(0, dtype=int)

    ext = [
        (a + 1 + b) // 2
        for a, b in zip(nonzero[:-1], nonzero[1:])
        if signs[a] != signs[b]
    ]
    return np.asarray(ext, dtype=int)


def _midpoints(x: np.ndarray, extrema: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Puntos medios ``f_1..f_{m-1}`` de los segmentos entre extremos adyacentes."""
    pos = (extrema[:-1] + extrema[1:]) / 2.0
    val = (x[extrema[:-1]] + x[extrema[1:]]) / 2.0
    return pos, val


def _with_boundaries(
    pos: np.ndarray, val: np.ndarray, n: int
) -> tuple[np.ndarray, np.ndarray]:
    """Añade ``f_0`` y ``f_m`` en los bordes por extrapolación lineal.

    El paper dice "supplement the midpoints of the left and right boundaries by
    interpolation" sin concretar. Usamos la recta que pasa por los dos puntos
    medios más cercanos a cada borde, que es la opción habitual en ESMD y evita
    el efecto de borde que el método presume corregir.
    """
    if pos.size >= 2:
        left = val[0] + (0.0 - pos[0]) * (val[1] - val[0]) / (pos[1] - pos[0])
        right = val[-1] + (n - 1 - pos[-1]) * (val[-1] - val[-2]) / (pos[-1] - pos[-2])
    else:
        left = right = float(val[0])

    return (
        np.concatenate(([0.0], pos, [float(n - 1)])),
        np.concatenate(([left], val, [right])),
    )


def _interpolate(pos: np.ndarray, val: np.ndarray, n: int) -> np.ndarray:
    """Spline cúbico sobre ``(pos, val)`` evaluado en 0..n-1.

    Con menos de 4 nodos un spline cúbico no está definido: se cae a lineal y,
    con un solo nodo, a curva constante.
    """
    grid = np.arange(n, dtype=float)
    keep = np.concatenate(([True], np.diff(pos) > 0))
    pos, val = pos[keep], val[keep]
    if pos.size >= 4:
        return cubic_spline_on_grid(pos, val, grid)
    if pos.size >= 2:
        return np.interp(grid, pos, val)
    return np.full(n, val[0] if val.size else 0.0)


def mean_curve(x: np.ndarray, n_curves: int) -> np.ndarray | None:
    """Curva media ``CSI`` de los ``C`` splines de puntos medios.

    El spline ``j`` se construye con los puntos medios interiores cuyo índice
    ``l`` cumple ``l ≡ j (mod C)``, más los dos puntos de borde — que es lo que
    denota ``{f_0, f_l, f_m}, j|l (C)`` en el Algoritmo 2.

    Devuelve ``None`` si la señal ya no tiene extremos suficientes (fin del
    tamizado).
    """
    x = np.asarray(x, dtype=float)
    extrema = find_extrema(x)
    if extrema.size < 2:
        return None

    pos, val = _midpoints(x, extrema)
    pos, val = _with_boundaries(pos, val, x.size)
    inner = np.arange(1, pos.size - 1)  # índices l = 1..m-1

    acc = np.zeros(x.size)
    for j in range(n_curves):
        picked = inner[inner % n_curves == j % n_curves]
        idx = np.concatenate(([0], picked, [pos.size - 1]))
        acc += _interpolate(pos[idx], val[idx], x.size)
    return acc / n_curves


def delta_threshold(x: np.ndarray, delta: float, mode: str = "range") -> float:
    """Traduce δ a un umbral absoluto sobre la escala de la señal."""
    x = np.asarray(x, dtype=float)
    if mode == "absolute":
        return float(delta)
    if mode == "std":
        scale = float(x.std())
    elif mode == "range":
        scale = float(x.max() - x.min())
    else:
        raise ValueError(f"delta_mode desconocido: {mode!r}")
    # Señal plana: cualquier umbral positivo sirve para terminar de inmediato.
    return float(delta) * scale if scale > 0 else np.inf


def sift(
    x: np.ndarray, n_curves: int, eps: float, max_iter: int, patience: int | None = 8
) -> np.ndarray:
    """Bucle interno del Algoritmo 2: resta ``CSI`` hasta que sea despreciable.

    Con precios reales el criterio ``max|CSI| ≤ δ`` no se alcanza: sobre una
    ventana de EUR/USD la amplitud de ``CSI`` cae unos cuatro órdenes de magnitud
    en ~9 pasadas y a partir de ahí **vuelve a crecer** (sobre-tamizado, el
    problema clásico de EMD: seguir tamizando destruye la IMF y la convierte en
    una oscilación modulada sin significado). Agotar las ``D = 100`` iteraciones
    del paper devolvería siempre esa versión degradada.

    Por eso se añaden dos salvaguardas a la formulación publicada:

    * **Mejor iterado**: se devuelve el ``Y`` con menor ``max|CSI|`` de todos los
      visitados, nunca el último sin más. Esta garantía es incondicional.
    * **Parada por estancamiento**: se abandona tras ``patience`` pasadas sin
      mejora. Es solo un ahorro de tiempo; con ``patience=None`` se recorren las
      ``max_iter`` pasadas del paper conservando la garantía anterior.

    La convergencia no es monótona (una pasada puede empeorar y la siguiente
    mejorar), de ahí que ``patience`` no pueda ser 1 ó 2 sin truncar
    convergencias legítimas.
    """
    y = np.asarray(x, dtype=float).copy()
    best_y, best_amp, stale = y, np.inf, 0

    # max_iter restas ⇒ max_iter+1 iterados, y todos se evalúan: el último
    # también compite por ser el mejor.
    for iteration in range(max_iter + 1):
        csi = mean_curve(y, n_curves)
        if csi is None or not np.isfinite(csi).all():
            break

        amplitude = float(np.max(np.abs(csi)))
        if amplitude < best_amp:
            best_y, best_amp, stale = y, amplitude, 0
        else:
            stale += 1
            if patience is not None and stale >= patience:
                break

        if amplitude <= eps or iteration == max_iter:
            break
        y = y - csi

    return best_y


def esmd(
    x: np.ndarray,
    n_curves: int = 2,
    delta: float = 0.001,
    max_iter: int = 100,
    phi: int = 6,
    max_imfs: int = 12,
    delta_mode: str = "range",
    patience: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Descompone ``x`` en IMFs y residuo (Algoritmo 2 completo).

    Se cumple por construcción ``sum(imfs) + residuo == x`` salvo error de coma
    flotante, lo que hace la descomposición reversible y verificable.

    Returns
    -------
    (imfs, residue) con ``imfs`` de forma ``(K, len(x))``.
    """
    x = np.asarray(x, dtype=float)
    eps = delta_threshold(x, delta, delta_mode)
    residue = x.copy()
    imfs: list[np.ndarray] = []

    while len(imfs) < max_imfs and find_extrema(residue).size > phi:
        imf = sift(residue, n_curves, eps, max_iter, patience)
        if not np.isfinite(imf).all():
            break
        imfs.append(imf)
        residue = residue - imf

    stacked = np.asarray(imfs) if imfs else np.empty((0, x.size))
    return stacked, residue


def first_imf(
    x: np.ndarray,
    n_curves: int = 2,
    delta: float = 0.001,
    max_iter: int = 100,
    delta_mode: str = "range",
    patience: int = 3,
) -> np.ndarray:
    """Solo la primera IMF — es lo único que CEESMDAN necesita en cada nivel."""
    x = np.asarray(x, dtype=float)
    eps = delta_threshold(x, delta, delta_mode)
    return sift(x, n_curves, eps, max_iter, patience)
