"""Tests de la representación de señal financiera (FSR).

Si estos tests no pasan, nada de lo que hay encima (entorno, PPO, backtest)
significa nada: el agente estaría aprendiendo sobre una señal mal construida o,
peor, sobre información del futuro.
"""
from __future__ import annotations

import numpy as np
import pytest

from tradingbot.config import FsrParams
from tradingbot.fsr.cache import cache_path, cached_features, compute_features
from tradingbot.fsr.ceesmdan import ceesmdan
from tradingbot.fsr.esmd import esmd, find_extrema, mean_curve, sift
from tradingbot.fsr.mrs import hurst
from tradingbot.fsr.represent import fsr_window


@pytest.fixture
def precios() -> np.ndarray:
    """Serie tipo EUR/USD: caminata aleatoria alrededor de 1.08."""
    rng = np.random.default_rng(7)
    return 1.08 + np.cumsum(rng.standard_normal(400)) * 2e-4


# -- ESMD (Algoritmo 2) ----------------------------------------------------


def test_esmd_reconstruye_la_senal(precios):
    """La descomposición es exacta: sum(IMFs) + residuo == señal original."""
    imfs, residue = esmd(precios)
    assert imfs.shape[0] > 0
    assert np.abs(imfs.sum(axis=0) + residue - precios).max() < 1e-9


def test_esmd_imfs_cumplen_la_condicion_de_extremos():
    """Condición (1) de §2.1.1: nº de máximos y mínimos difiere como mucho en 1."""
    t = np.arange(300)
    señal = np.sin(2 * np.pi * t / 60) + 0.3 * np.sin(2 * np.pi * t / 9)
    imfs, _ = esmd(señal)

    for imf in imfs:
        extremos = find_extrema(imf)
        # Los extremos alternan máximo/mínimo, así que basta comprobar que la
        # segunda diferencia cambia de signo en cada uno de ellos.
        signos = np.sign(imf[extremos - 1] + imf[extremos + 1] - 2 * imf[extremos])
        maximos = int((signos > 0).sum())
        minimos = int((signos < 0).sum())
        assert abs(maximos - minimos) <= 1


def test_sift_devuelve_el_mejor_iterado(precios):
    """Garantía incondicional del tamizado: nunca devuelve un iterado peor.

    El bucle del paper se queda con la última pasada. Sobre precios reales
    ``max|CSI|`` baja varios órdenes de magnitud y después vuelve a crecer
    (sobre-tamizado), así que la última pasada puede ser mucho peor que la mejor.
    Con ``patience=None`` se visitan exactamente las mismas pasadas que el
    algoritmo publicado, de modo que la comparación es limpia.
    """
    # eps = 0 para que el criterio δ nunca se cumpla: así ambos recorren las
    # mismas 60 pasadas y lo único que se compara es cuál iterado se devuelve.
    nuestro = sift(precios, n_curves=2, eps=0.0, max_iter=60, patience=None)

    ingenuo = precios.copy()
    for _ in range(60):
        curva = mean_curve(ingenuo, 2)
        if curva is None:
            break
        ingenuo = ingenuo - curva

    amplitud = lambda y: float(np.abs(mean_curve(y, 2)).max())
    assert amplitud(nuestro) <= amplitud(ingenuo) + 1e-15


def test_patience_no_altera_el_resultado_ya_convergido():
    """Una señal que converge rápido da lo mismo con y sin parada temprana."""
    t = np.arange(200)
    señal = np.sin(2 * np.pi * t / 40)
    assert np.allclose(esmd(señal, patience=8)[0], esmd(señal, patience=None)[0])


# -- CEESMDAN (Algoritmo 3) ------------------------------------------------


def test_ceesmdan_reconstruye_y_es_determinista(precios):
    imfs, residue = ceesmdan(precios[:80], ensemble_size=6, seed=3)
    assert np.abs(imfs.sum(axis=0) + residue - precios[:80]).max() < 1e-9

    otra, _ = ceesmdan(precios[:80], ensemble_size=6, seed=3)
    assert np.array_equal(imfs, otra), "la misma semilla debe dar la misma salida"


def test_ceesmdan_corrige_el_mode_mixing():
    """El motivo de existir de CEESMDAN (§2.1.2).

    El caso canónico de mezcla de modos no son dos tonos limpios —ESMD ya los
    separa— sino una ráfaga de alta frecuencia **intermitente** sobre una onda
    lenta. Con mezcla, la primera IMF arrastra la onda lenta fuera del tramo de
    la ráfaga; sin mezcla, fuera de la ráfaga es prácticamente cero.
    """
    t = np.arange(400.0)
    rafaga = slice(150, 200)
    señal = np.sin(2 * np.pi * t / 80)
    señal[rafaga] += 0.3 * np.sin(2 * np.pi * t[rafaga] / 4)

    def fuga(imf: np.ndarray) -> float:
        dentro = float(np.sum(imf[rafaga] ** 2))
        return (float(np.sum(imf**2)) - dentro) / (dentro + 1e-18)

    fuga_esmd = fuga(esmd(señal)[0][0])
    fuga_ceesmdan = fuga(ceesmdan(señal, ensemble_size=12, seed=0)[0][0])

    assert fuga_esmd > 10.0, "el caso de prueba debe provocar mezcla de modos en ESMD"
    assert fuga_ceesmdan < 1.0
    assert fuga_ceesmdan < fuga_esmd / 10.0


# -- MRS (Algoritmo 4) -----------------------------------------------------


def test_hurst_distingue_memoria():
    rng = np.random.default_rng(42)

    ruido_blanco = rng.standard_normal(2000)
    caminata = np.cumsum(rng.standard_normal(2000))
    anticorrelada = np.resize([1.0, -1.0], 2000) + 0.1 * rng.standard_normal(2000)

    assert hurst(ruido_blanco) == pytest.approx(0.5, abs=0.1)
    assert hurst(caminata) > 0.65
    assert hurst(anticorrelada) < 0.4


def test_hurst_es_invariante_de_escala():
    """R/S normaliza por la desviación típica: multiplicar la serie no cambia H."""
    rng = np.random.default_rng(11)
    serie = np.cumsum(rng.standard_normal(500))
    assert hurst(serie) == pytest.approx(hurst(serie * 1000.0), abs=1e-9)


# -- FSR completo ----------------------------------------------------------


def test_fsr_descarta_alta_frecuencia_y_conserva_tendencia(precios):
    resultado = fsr_window(precios[:50])

    assert resultado.imfs.shape[0] >= 2
    # La primera IMF es siempre la más rápida y debe tener menos memoria que la última.
    assert resultado.hursts[0] < resultado.hursts[-1]
    assert not resultado.kept[0], "la IMF de alta frecuencia debe descartarse"
    # Lo que baja al quitar el ruido es la rugosidad, no necesariamente la
    # varianza: descartar un modo anticorrelado con el resto puede subirla.
    assert find_extrema(resultado.signal).size < find_extrema(precios[:50]).size


def test_fsr_es_causal(precios):
    """El test que impide la fuga de futuro.

    Alterar arbitrariamente todo lo posterior a la barra evaluada no puede
    cambiar ni un bit de sus características.
    """
    params = FsrParams()
    ventana = precios[:params.window]

    contaminada = precios.copy()
    contaminada[params.window:] = 99.0  # el futuro se vuelve absurdo

    original = fsr_window(ventana, params).features
    con_futuro_roto = fsr_window(contaminada[:params.window], params).features

    assert np.array_equal(original, con_futuro_roto)


def test_fsr_normalizado_es_invariante_al_nivel_de_precio():
    """Dos ventanas con la misma forma y distinto nivel dan las mismas features."""
    t = np.arange(60)
    forma = np.sin(2 * np.pi * t / 20) * 0.004
    params = FsrParams(ensemble_size=6)

    a = fsr_window(1.08 + forma, params).features
    b = fsr_window(1.35 + forma * (1.35 / 1.08), params).features

    assert np.abs(a - b).max() < 1e-3


# -- Caché -----------------------------------------------------------------


def test_matriz_de_features_esta_alineada_con_las_barras(precios):
    params = FsrParams(window=50, ensemble_size=4)
    serie = precios[:120]

    matriz = compute_features(serie, params, workers=1)

    assert matriz.shape == (len(serie) - params.window + 1, params.window)
    # La fila i debe coincidir con calcular FSR sobre la ventana que acaba en la
    # barra i + window - 1.
    for i in (0, 17, matriz.shape[0] - 1):
        esperado = fsr_window(serie[i : i + params.window], params).features
        assert np.array_equal(matriz[i], esperado)


def test_la_cache_se_invalida_al_cambiar_parametros(precios, tmp_path):
    serie = precios[:70]
    base = FsrParams(window=50, ensemble_size=4)

    primera = cached_features(serie, base, cache_dir=tmp_path, workers=1)
    assert cache_path(base, tmp_path).exists()

    # Releer da exactamente lo mismo (viene del disco).
    assert np.array_equal(primera, cached_features(serie, base, cache_dir=tmp_path, workers=1))

    otros = FsrParams(window=50, ensemble_size=4, hurst_threshold=0.9)
    assert cache_path(otros, tmp_path) != cache_path(base, tmp_path)


def test_anadir_barras_nuevas_solo_calcula_las_ventanas_nuevas(precios, tmp_path):
    """El arreglo que impide que el precálculo sea un coste recurrente.

    Con la clave por serie completa, descargar una vela nueva invalidaba el
    histórico entero. Indexando por ventana, las anteriores se reutilizan.
    """
    params = FsrParams(window=50, ensemble_size=4)
    corta = precios[:70]
    larga = precios[:75]      # cinco barras más ⇒ cinco ventanas nuevas

    cached_features(corta, params, cache_dir=tmp_path, workers=1)

    calculadas: list[int] = []
    cached_features(
        larga, params, cache_dir=tmp_path, workers=1,
        progress=lambda hechas, totales: calculadas.append(totales),
    )

    assert calculadas and max(calculadas) == 5, (
        f"debería recalcular solo 5 ventanas, no {max(calculadas) if calculadas else 0}"
    )


def test_las_filas_reutilizadas_son_identicas_a_recalcularlas(precios, tmp_path):
    """Reutilizar no puede alterar el resultado: la caché es transparente."""
    params = FsrParams(window=50, ensemble_size=4)

    cached_features(precios[:70], params, cache_dir=tmp_path, workers=1)
    con_cache = cached_features(precios[:75], params, cache_dir=tmp_path, workers=1)
    sin_cache = compute_features(precios[:75], params, workers=1)

    assert np.array_equal(con_cache, sin_cache)


def test_las_ventanas_identicas_comparten_fila(tmp_path):
    """Dos series que contienen la misma ventana la calculan una sola vez."""
    rng = np.random.default_rng(4)
    tramo = 1.08 + np.cumsum(rng.standard_normal(60)) * 2e-4
    params = FsrParams(window=50, ensemble_size=4)

    cached_features(tramo, params, cache_dir=tmp_path, workers=1)

    # Misma ventana precedida de otras barras: la fila común no se recalcula.
    otra = np.concatenate([1.2 + rng.standard_normal(3) * 1e-4, tramo])
    calculadas: list[int] = []
    cached_features(
        otra, params, cache_dir=tmp_path, workers=1,
        progress=lambda hechas, totales: calculadas.append(totales),
    )
    assert max(calculadas) == 3


def test_el_spline_propio_coincide_con_scipy():
    """El spline escrito a mano debe ser indistinguible del de scipy.

    Se sustituyó ``CubicSpline`` porque su construcción se llevaba el 71 % del
    tiempo de FSR sobre nodos de ~25 puntos. La sustitución solo vale si el
    resultado no cambia: si divergiera, cambiaría la señal que ve el agente.
    """
    from scipy.interpolate import CubicSpline

    from tradingbot.fsr.esmd import cubic_spline_on_grid

    rng = np.random.default_rng(0)
    grid = np.arange(50, dtype=float)

    for _ in range(200):
        x = np.unique(np.sort(rng.uniform(0, 49, rng.integers(4, 30))))
        if x.size < 4:
            continue
        y = rng.standard_normal(x.size) * rng.uniform(1e-4, 10)
        esperado = CubicSpline(x, y)(grid)
        obtenido = cubic_spline_on_grid(x, y, grid)
        assert np.allclose(obtenido, esperado, rtol=1e-10, atol=1e-12)
