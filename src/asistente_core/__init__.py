"""Núcleo reutilizable del asistente de datos para dashboards FastAPI."""
from .config import asistente_activo
from .prompts import construir_instrucciones_reporte, construir_system_prompt

from .toolkit import Atajo, Toolkit

__version__ = "0.4.2"


def crear_router(*args, **kwargs):
    """Router de FastAPI (import perezoso: un proyecto Django no necesita tener FastAPI instalado)."""
    from .router import crear_router as _crear_router
    return _crear_router(*args, **kwargs)


__all__ = ["Atajo", "Toolkit", "asistente_activo", "construir_instrucciones_reporte", "construir_system_prompt", "crear_router", "__version__"]
