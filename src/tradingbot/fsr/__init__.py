"""FSR — Financial Signal Representation (§2.1 del paper FSRPPO).

CEESMDAN descompone la señal de precio, MRS mide la memoria de cada modo y la
reconstrucción se queda solo con los de memoria larga.
"""
from .ceesmdan import ceesmdan
from .esmd import esmd, find_extrema
from .mrs import hurst
from .represent import FsrResult, fsr_features, fsr_window

__all__ = [
    "ceesmdan",
    "esmd",
    "find_extrema",
    "hurst",
    "FsrResult",
    "fsr_features",
    "fsr_window",
]
