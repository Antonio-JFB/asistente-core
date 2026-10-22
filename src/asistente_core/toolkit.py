"""
Toolkit: el "contrato" entre el núcleo del asistente y un dashboard concreto.

Cada dashboard le entrega al núcleo tres cosas: la lista de herramientas que el
modelo puede pedir (`schemas`), las funciones de Python que las ejecutan
(`functions`) y el system prompt. El núcleo nunca sabe nada de las columnas ni
del dominio del dashboard; solo ejecuta lo que el Toolkit le dice.

Esta clase concentra la lógica que NO debe variar entre dashboards:
- validar al arrancar que cada herramienta declarada tiene su función (y al revés);
- corregir los tipos de los argumentos que mandan algunos modelos;
- ocultarle al modelo las tablas de detalle de un reporte.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

_PLACEHOLDER_TABLA = (
    "(oculto a propósito: esta tabla ya se muestra aparte, con las cifras reales, "
    "debajo del reporte; no transcribas montos ni identificadores individuales, "
    "solo remite a esa tabla)"
)


def _coerce(valor, tipo: str | None):
    """Algunos modelos (sobre todo por Ollama) regresan argumentos como string
    aunque el schema pida boolean/integer/number (ej. excluir_gc: "false"),
    y un string no vacío es verdadero en Python: sin esto, "false" activaría
    un filtro por accidente. Se corrige comparando contra el tipo declarado
    en el schema antes de invocar la función."""
    if not isinstance(valor, str) or tipo not in {"boolean", "integer", "number"}:
        return valor
    try:
        if tipo == "boolean":
            return valor.strip().lower() in {"true", "1", "yes", "si", "sí"}
        if tipo == "integer":
            return int(float(valor))
        return float(valor)
    except ValueError:
        return valor


_INSTRUCCION_ERROR = (
    "No inventes ningún dato. Dile al usuario, en una frase, que no pudiste obtener esa "
    "información con las herramientas disponibles, y menciona qué sí puedes consultar."
)

_TEXTOS_SIN_VALOR = {"", "null", "none", "undefined", "n/a"}


def _sin_valor(valor, tipo: str | None) -> bool:
    """Un modelo a veces manda un parámetro opcional como null (o "null") en vez de
    omitirlo; la función entonces recibe None y truena (ej. int(None)). Eso significa
    "no lo mandé": se descarta para que aplique el valor por defecto de la función.
    En parámetros de texto, "" sí es un valor válido y se respeta."""
    if valor is None:
        return True
    return isinstance(valor, str) and tipo != "string" and valor.strip().lower() in _TEXTOS_SIN_VALOR


@dataclass
class Toolkit:
    schemas: list[dict]
    """Definiciones de herramientas en formato Anthropic: name, description, input_schema."""

    functions: dict[str, Callable]
    """nombre -> función(request, **argumentos) que regresa un dict serializable a JSON."""

    system_prompt: str
    """Texto completo del system prompt (ver `construir_system_prompt`)."""

    nombre_app: str = ""
    """Nombre del dashboard, para el encabezado de los reportes extensos."""

    nota_reporte: str = ""
    """Frase propia del dashboard para el pie de los reportes (ej. aclaraciones metodológicas)."""

    ocultar_al_modelo: tuple[str, ...] = ("tabla_detalle",)
    """Campos de un resultado de reporte que el modelo NO debe ver (se siguen
    mostrando al usuario). Ver `para_llm`."""

    instrucciones_reporte: str = ""
    """Cómo redactar el reporte largo (ver `construir_instrucciones_reporte`). Se entrega al
    modelo SOLO dentro del resultado de un reporte, no en el system prompt."""

    contexto_redactor: str = ""
    """Una o dos frases del dominio para el modelo redactor (ver redactor.py), por ejemplo qué
    miden los scores. Sin esto el redactor describe los datos con vocabulario genérico."""

    def __post_init__(self):
        con_schema = {t["name"] for t in self.schemas}
        con_funcion = set(self.functions)
        sin_funcion = sorted(con_schema - con_funcion)
        sin_schema = sorted(con_funcion - con_schema)
        if sin_funcion or sin_schema:
            raise ValueError(
                "El Toolkit no cuadra: "
                f"herramientas declaradas sin función: {sin_funcion or 'ninguna'}; "
                f"funciones sin declarar en schemas: {sin_schema or 'ninguna'}. "
                "El 'name' de cada schema debe ser idéntico a la llave en `functions`."
            )
        self._propiedades = {
            t["name"]: t["input_schema"].get("properties", {}) for t in self.schemas
        }

    def ejecutar(self, nombre: str, args: dict | None, request) -> dict:
        fn = self.functions.get(nombre)
        if fn is None:
            return {"error": f"Herramienta desconocida: {nombre}"}
        propiedades = self._propiedades.get(nombre, {})
        normalizados = {
            k: _coerce(v, propiedades.get(k, {}).get("type"))
            for k, v in (args or {}).items()
            if not _sin_valor(v, propiedades.get(k, {}).get("type"))
        }
        try:
            return fn(request, **normalizados)
        except TypeError as e:
            desconocidos = sorted(set(normalizados) - set(propiedades))
            if desconocidos:
                # Los modelos agregan parámetros que no existen (ej. excluir_gc en todas las
                # herramientas). Antes el error no decía cuáles eran los válidos y el modelo
                # lo contaba como "no puedo". Ahora se le dice cómo corregir la llamada.
                return {
                    "error": f"La herramienta '{nombre}' no acepta los parámetros {desconocidos}. "
                             f"Parámetros válidos: {sorted(propiedades) or 'ninguno'}.",
                    "instruccion": "Vuelve a llamar a la herramienta usando solo los parámetros válidos. "
                                   "No inventes datos.",
                }
            return {"error": f"Parámetros inválidos para '{nombre}': {e}"}
        except Exception as e:
            return {"error": f"No se pudo ejecutar '{nombre}': {e}"}

    def para_llm(self, resultado):
        """Copia del resultado que verá el modelo para redactar su respuesta.

        En un resultado de reporte (el que trae `chart_specs`):
        - se reemplazan los campos de `ocultar_al_modelo` por un aviso. Dárselos crudos
          al modelo, aun pidiéndole en el prompt que no los transcriba, llevó en pruebas
          reales a que inventara montos o los multiplicara por 1000. La tabla real que
          ve el usuario se arma aparte, con el resultado SIN filtrar;
        - se agregan las instrucciones de redacción del reporte, para que el modelo las
          vea solo cuando de verdad va a escribir un reporte."""
        if isinstance(resultado, dict) and "error" in resultado and "instruccion" not in resultado:
            # Tras un error el modelo tendía a inventar la respuesta (cifras y tablas falsas).
            return {**resultado, "instruccion": _INSTRUCCION_ERROR}
        if not isinstance(resultado, dict) or "chart_specs" not in resultado:
            return resultado
        visto = dict(resultado)
        for k in self.ocultar_al_modelo:
            if k in visto:
                visto[k] = _PLACEHOLDER_TABLA
        if self.instrucciones_reporte:
            visto["instrucciones_de_redaccion"] = self.instrucciones_reporte
        return visto
