"""
Backend Claude (API de Anthropic) para el asistente.

Mismo contrato que providers/ollama_provider.py: responder(mensaje, historial,
request, toolkit) -> {reply, chart_spec, tabla, reporte_data, historial,
tool_trace}. El formato de `historial` es el de bloques de contenido de
Anthropic — no se mezcla con el historial del proveedor Ollama.
"""
from __future__ import annotations

import json
import os

from ..costos import costo_usd
from ..toolkit import Toolkit

# `or` y no el default de getenv: un ASISTENTE_MODEL= vacío en el .env no debe dejar el modelo en "".
MODEL = os.getenv("ASISTENTE_MODEL") or "claude-sonnet-5-5"
# Esfuerzo de razonamiento del modelo: más bajo = más barato y rápido. "ninguno" no envía el parámetro
# (modelos que no lo soportan). Se midió con la batería antes de fijar el default.
EFFORT = os.getenv("ASISTENTE_EFFORT") or "medium"
MAX_TURNOS = 5
# Un reporte extenso (~900 palabras en español) ronda 1300-1500 tokens de salida;
# 1024 lo truncaría a media narrativa.
MAX_TOKENS_RESPUESTA = 4096

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("Falta configurar ANTHROPIC_API_KEY en el entorno (.env).")
        from anthropic import Anthropic  # import perezoso: no requerido hasta el primer chat
        _client = Anthropic(api_key=api_key)
    return _client


def parametros_extra() -> dict:
    """Parámetros opcionales comunes a toda llamada a Claude (esfuerzo de razonamiento)."""
    return {} if EFFORT.lower() in ("ninguno", "none", "off") else {"output_config": {"effort": EFFORT}}


def _sin_pensamiento(mensajes: list[dict]) -> list[dict]:
    """El historial que viaja al navegador no lleva los bloques de razonamiento del modelo: sirven solo
    dentro del turno que los produjo, y el texto de la respuesta puede ser reescrito (modelo redactor)."""
    limpio = []
    for m in mensajes:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            bloques = [b for b in m["content"] if b.get("type") not in ("thinking", "redacted_thinking")]
            m = {**m, "content": bloques}
        limpio.append(m)
    return limpio


def responder(mensaje: str, historial: list[dict], request, toolkit: Toolkit) -> dict:
    """Ejecuta el loop de tool-calling y regresa la respuesta final, más tabla/gráfica si aplica."""
    client = _get_client()
    messages = [*historial, {"role": "user", "content": mensaje}]

    chart_spec = None
    tabla = None
    reporte_data = None
    tool_trace = []
    uso = {"modelo": MODEL, "llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0, "costo_usd": 0.0}

    def contar(resp):
        u = resp.usage
        entrada = getattr(u, "input_tokens", 0) or 0
        salida = getattr(u, "output_tokens", 0) or 0
        c_lect = getattr(u, "cache_read_input_tokens", 0) or 0
        c_escr = getattr(u, "cache_creation_input_tokens", 0) or 0
        uso["llamadas"] += 1
        uso["tokens_entrada"] += entrada + c_lect + c_escr
        uso["tokens_salida"] += salida
        uso["costo_usd"] += costo_usd(MODEL, entrada, salida, c_lect, c_escr) or 0.0

    extra = parametros_extra()

    for _ in range(MAX_TURNOS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_RESPUESTA,
            system=toolkit.system_prompt,
            tools=toolkit.schemas,
            messages=messages,
            **extra,
        )
        contar(resp)

        contenido = [bloque.model_dump() for bloque in resp.content]

        if resp.stop_reason != "tool_use":
            texto = "".join(b["text"] for b in contenido if b.get("type") == "text")
            return {
                "reply": texto,
                "chart_spec": chart_spec,
                "tabla": tabla,
                "reporte_data": reporte_data,
                "historial": _sin_pensamiento([*messages, {"role": "assistant", "content": contenido}]),
                "tool_trace": tool_trace,
                "uso": uso,
            }

        messages.append({"role": "assistant", "content": contenido})

        resultados_tool = []
        for bloque in contenido:
            if bloque.get("type") != "tool_use":
                continue
            resultado = toolkit.ejecutar(bloque["name"], bloque.get("input") or {}, request)
            tool_trace.append({"tool": bloque["name"], "args": bloque.get("input")})

            if isinstance(resultado, dict):
                if "chart_specs" in resultado:
                    reporte_data = resultado
                elif "chart_spec" in resultado:
                    chart_spec = resultado["chart_spec"]
                if "cuentas" in resultado:
                    tabla = resultado["cuentas"]
                elif "colonias" in resultado:
                    tabla = resultado["colonias"]

            resultados_tool.append({
                "type": "tool_result",
                "tool_use_id": bloque["id"],
                "content": json.dumps(toolkit.para_llm(resultado), ensure_ascii=False, default=str),
            })

        messages.append({"role": "user", "content": resultados_tool})

    return {
        "reply": "No pude completar la respuesta en el número de pasos permitido. Intenta reformular la pregunta.",
        "chart_spec": chart_spec,
        "tabla": tabla,
        "reporte_data": reporte_data,
        "historial": _sin_pensamiento(messages),
        "tool_trace": tool_trace,
        "uso": uso,
    }
