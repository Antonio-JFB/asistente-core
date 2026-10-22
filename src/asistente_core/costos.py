"""Costo aproximado de las llamadas a la API de Claude, para poder vigilar el gasto."""
from __future__ import annotations

# USD por millón de tokens (entrada, salida). Precios de lista; si cambian, actualiza esta tabla.
PRECIOS_USD_POR_MILLON = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def costo_usd(modelo: str, entrada: int, salida: int, cache_lectura: int = 0, cache_escritura: int = 0) -> float | None:
    """Costo en USD de una llamada, o None si el modelo no está en la tabla.

    `entrada` son los tokens de entrada normales; la caché se cobra aparte (lectura a 10 % del precio
    de entrada, escritura a 125 %).
    """
    precios = PRECIOS_USD_POR_MILLON.get(modelo)
    if precios is None:
        return None
    p_in, p_out = precios
    return (entrada * p_in + cache_lectura * p_in * 0.1 + cache_escritura * p_in * 1.25 + salida * p_out) / 1e6
