"""Interruptor general del asistente."""
from __future__ import annotations

import os

_SI = {"1", "true", "si", "sí", "yes", "on"}


def asistente_activo() -> bool:
    """El asistente solo funciona si ASISTENTE_ACTIVO está en 1 (apagado por defecto).

    Así el código se puede llevar a producción sin que nadie lo vea: apagado, el router no
    expone ninguna ruta y el botón de chat no se muestra. Se lee al arrancar la aplicación,
    por lo que prenderlo o apagarlo requiere reiniciar el servicio.
    """
    return os.getenv("ASISTENTE_ACTIVO", "").strip().lower() in _SI
