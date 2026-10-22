"""Núcleo reutilizable del asistente de datos para dashboards FastAPI."""
from .config import asistente_activo
from .prompts import construir_instrucciones_reporte, construir_system_prompt
from .router import crear_router
from .toolkit import Toolkit

__version__ = "0.2.1"
__all__ = ["Toolkit", "asistente_activo", "construir_instrucciones_reporte", "construir_system_prompt", "crear_router", "__version__"]
