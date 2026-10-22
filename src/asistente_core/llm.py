"""
Punto de entrada del asistente: elige el proveedor de LLM según la variable de
entorno ASISTENTE_PROVIDER ("anthropic" | "ollama", default "anthropic") y
delega en el módulo correspondiente.

Ambos proveedores implementan la misma firma:

    responder(mensaje, historial, request, toolkit) -> dict
    # {reply, chart_spec, tabla, reporte_data, historial, tool_trace}

El Toolkit trae las herramientas del dashboard; lo único que cambia entre
proveedores es qué modelo decide cuál usar.
"""
from __future__ import annotations

import os

from .toolkit import Toolkit


def responder(mensaje: str, historial: list[dict], request, toolkit: Toolkit) -> dict:
    # Se lee en cada llamada (no al importar) para que el cambio de variable
    # de entorno surta efecto sin depender del orden de los imports.
    if os.getenv("ASISTENTE_PROVIDER", "anthropic").strip().lower() == "ollama":
        from .providers.ollama_provider import responder as _responder
    else:
        from .providers.anthropic_provider import responder as _responder
    return _responder(mensaje, historial, request, toolkit)
