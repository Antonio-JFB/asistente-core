"""
Backend local con Ollama para el asistente (sin llamadas a ningún servicio
externo: todo corre contra el daemon de Ollama en esta misma máquina/red).

Mismo contrato que providers/anthropic_provider.py: responder(mensaje,
historial, request, toolkit) -> {reply, chart_spec, tabla, reporte_data,
historial, tool_trace}. El formato de `historial` es el de la API de chat de
Ollama (mensajes con tool_calls / role "tool") — no se mezcla con el historial
del proveedor Anthropic; el cliente solo debe reenviar lo que este mismo
servidor le entregó.

Requiere un modelo con soporte de "tools" cargado en Ollama. De los modelos
usados para probar esto, `mistral` y `llama3.2` sí lo soportan; `gemma3` no
(revisar con `ollama show <modelo>` → sección "Capabilities").
"""
from __future__ import annotations

import json
import os

from ..toolkit import Toolkit

MODEL = os.getenv("ASISTENTE_MODEL_OLLAMA", "mistral")
HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MAX_TURNOS = 5
# Un reporte extenso necesita bastante más que la respuesta corta típica;
# -1 (default de Ollama) genera hasta encontrar el token de fin, sin tope
# artificial de longitud.
NUM_PREDICT = -1

_client = None


def _get_client():
    global _client
    if _client is None:
        import ollama  # import perezoso: no requerido hasta el primer chat
        _client = ollama.Client(host=HOST)
    return _client


def _tools_ollama(schemas: list[dict]) -> list[dict]:
    """Convierte el catálogo (formato Anthropic) al formato OpenAI-style que usa Ollama."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in schemas
    ]


def responder(mensaje: str, historial: list[dict], request, toolkit: Toolkit) -> dict:
    client = _get_client()
    tools = _tools_ollama(toolkit.schemas)

    if not historial:
        historial = [{"role": "system", "content": toolkit.system_prompt}]
    messages = [*historial, {"role": "user", "content": mensaje}]

    chart_spec = None
    tabla = None
    reporte_data = None
    tool_trace = []

    for _ in range(MAX_TURNOS):
        # Temperatura baja a propósito: este loop necesita que el modelo siga
        # instrucciones y formatee parámetros de forma consistente, no que
        # sea creativo. Con la temperatura por default se observó la misma
        # pregunta dando resultados distintos entre corridas (a veces llama
        # bien la herramienta, a veces alucina la respuesta completa).
        resp = client.chat(
            model=MODEL, messages=messages, tools=tools,
            # repeat_penalty por encima del default (1.1): en un reporte extenso
            # real, llama3.2 degeneró en viñetas repetitivas sin contenido
            # ("no se incluye información sobre las limitaciones y alcance").
            options={"temperature": 0.1, "num_predict": NUM_PREDICT, "repeat_penalty": 1.3},
        )
        msg = resp["message"]
        llamadas = msg.get("tool_calls") or []

        if not llamadas:
            messages.append({"role": "assistant", "content": msg.get("content", "")})
            return {
                "reply": msg.get("content", ""),
                "chart_spec": chart_spec,
                "tabla": tabla,
                "reporte_data": reporte_data,
                "historial": messages,
                "tool_trace": tool_trace,
            }

        messages.append({
            "role": "assistant",
            "content": msg.get("content", ""),
            "tool_calls": llamadas,
        })

        for llamada in llamadas:
            nombre = llamada["function"]["name"]
            args = llamada["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            resultado = toolkit.ejecutar(nombre, args, request)
            tool_trace.append({"tool": nombre, "args": args})

            if isinstance(resultado, dict):
                if "chart_specs" in resultado:
                    reporte_data = resultado
                elif "chart_spec" in resultado:
                    chart_spec = resultado["chart_spec"]
                if "cuentas" in resultado:
                    tabla = resultado["cuentas"]
                elif "colonias" in resultado:
                    tabla = resultado["colonias"]

            messages.append({
                "role": "tool",
                "content": json.dumps(toolkit.para_llm(resultado), ensure_ascii=False, default=str),
            })

    return {
        "reply": "No pude completar la respuesta en el número de pasos permitido. Intenta reformular la pregunta.",
        "chart_spec": chart_spec,
        "tabla": tabla,
        "reporte_data": reporte_data,
        "historial": messages,
        "tool_trace": tool_trace,
    }
