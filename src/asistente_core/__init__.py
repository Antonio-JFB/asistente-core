"""Núcleo reutilizable del asistente de datos para dashboards FastAPI."""
from .config import asistente_activo
from .prompts import construir_instrucciones_reporte, construir_system_prompt
from .router import crear_router
from .toolkit import Atajo, Toolkit

__version__ = "0.3.1"
__all__ = ["Atajo", "Toolkit", "asistente_activo", "construir_instrucciones_reporte", "construir_system_prompt", "crear_router", "__version__"]
