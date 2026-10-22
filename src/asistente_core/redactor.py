"""
Modelo redactor (opcional): un segundo modelo que escribe SOLO el reporte largo.

El modelo principal es bueno para elegir herramientas y malo para redactar texto largo (con
llama3.2: 187-310 palabras cuando se piden 700-900). El redactor recibe únicamente las
instrucciones y los datos agregados del reporte (nunca la tabla de cuentas ni las gráficas) y
escribe la narrativa. Con gemma3:12b: 734-858 palabras, todas las secciones y ninguna cifra
inventada en 6 de 6 corridas. gemma3 no sabe usar herramientas, pero para redactar no hace falta.

Se activa según el proveedor (ASISTENTE_PROVIDER):
  ollama     -> ASISTENTE_MODEL_REDACTOR_OLLAMA (ej. "gemma3:12b")
  anthropic  -> ASISTENTE_MODEL_REDACTOR        (ej. "claude-sonnet-5-5")
Vacío = desactivado: el reporte lo escribe el modelo principal. Si el redactor falla (Ollama apagado,
sin saldo en la API), se usa la respuesta del modelo principal en vez de dejar al usuario sin reporte.
Con Claude el modelo principal escribía ~500 palabras (se piden 700-900); una llamada aparte, sin
herramientas, da 960-980, sin especulación ni cifras inventadas, por ~3 centavos más.
"""
from __future__ import annotations

import json
import os

from .toolkit import Toolkit

# Se midió (gemma3:12b, 6 reportes por configuración) agregar aquí "no especules sobre causas...":
# quitaba la especulación pero acortaba los reportes de 804 a 510 palabras (se piden 700-900).
# Lo que corrige el encuadre sin acortar es el contexto del dominio (Toolkit.contexto_redactor):
# 805 palabras y "no es riesgo crediticio" en 6 de 6. No agregues reglas aquí sin medir.
SISTEMA_BASE = "Eres un redactor de reportes de datos. Responde siempre en español."

# gemma3:12b ocupa 8 GB de una GPU de 12 GB: se libera pronto para no frenar la computadora.
KEEP_ALIVE = "1m"


def _proveedor() -> str:
    return (os.getenv("ASISTENTE_PROVIDER") or "anthropic").strip().lower()


def modelo_configurado() -> str:
    variable = "ASISTENTE_MODEL_REDACTOR_OLLAMA" if _proveedor() == "ollama" else "ASISTENTE_MODEL_REDACTOR"
    return os.getenv(variable, "").strip()


def _cliente():
    import ollama  # import perezoso: solo si hay redactor configurado
    return ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))


def entrada_redactor(toolkit: Toolkit, reporte_data: dict) -> str:
    """Lo único que ve el redactor: instrucciones + datos agregados (sin gráficas ni tabla de cuentas)."""
    visto = toolkit.para_llm(reporte_data)
    instrucciones = visto.pop("instrucciones_de_redaccion", toolkit.instrucciones_reporte)
    visto.pop("chart_specs", None)
    return (
        f"{instrucciones}\n\nDATOS DEL REPORTE (JSON):\n"
        f"{json.dumps(visto, ensure_ascii=False, default=str)}\n\nRedacta el reporte ahora."
    )


def _redactar_claude(modelo: str, sistema: str, entrada: str) -> tuple[str | None, dict]:
    from .costos import costo_usd
    from .providers import anthropic_provider as ap
    r = ap._get_client().messages.create(
        model=modelo, max_tokens=ap.MAX_TOKENS_RESPUESTA, system=sistema,
        messages=[{"role": "user", "content": entrada}], **ap.parametros_extra(),
    )
    texto = "".join(b.text for b in r.content if b.type == "text").strip() or None
    u = r.usage
    entrada_t, salida_t = u.input_tokens or 0, u.output_tokens or 0
    uso = {"modelo": modelo, "llamadas": 1, "tokens_entrada": entrada_t, "tokens_salida": salida_t,
           "costo_usd": costo_usd(modelo, entrada_t, salida_t) or 0.0}
    return texto, uso


def redactar_con_uso(toolkit: Toolkit, reporte_data: dict) -> tuple[str | None, dict | None]:
    """(narrativa, uso). La narrativa es None si no hay redactor o si falló; `uso` solo existe con Claude."""
    modelo = modelo_configurado()
    if not modelo:
        return None, None
    sistema = f"{toolkit.contexto_redactor} {SISTEMA_BASE}".strip()
    entrada = entrada_redactor(toolkit, reporte_data)
    try:
        if _proveedor() == "ollama":
            r = _cliente().chat(
                model=modelo,
                keep_alive=KEEP_ALIVE,
                options={"temperature": 0.1, "num_predict": -1},
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": entrada},
                ],
            )
            return (r["message"]["content"] or "").strip() or None, None
        return _redactar_claude(modelo, sistema, entrada)
    except Exception as e:
        print(f"ADVERTENCIA: el modelo redactor '{modelo}' falló ({type(e).__name__}: {e}); "
              "se usa la respuesta del modelo principal.", flush=True)
        return None, None


def redactar(toolkit: Toolkit, reporte_data: dict) -> str | None:
    """Narrativa del reporte escrita por el redactor, o None si no hay redactor o si falló."""
    return redactar_con_uso(toolkit, reporte_data)[0]
