"""
Modelo redactor (opcional): un segundo modelo que escribe SOLO el reporte largo.

El modelo principal es bueno para elegir herramientas y malo para redactar texto largo (con
llama3.2: 187-310 palabras cuando se piden 700-900). El redactor recibe únicamente las
instrucciones y los datos agregados del reporte (nunca la tabla de cuentas ni las gráficas) y
escribe la narrativa. Con gemma3:12b: 734-858 palabras, todas las secciones y ninguna cifra
inventada en 6 de 6 corridas. gemma3 no sabe usar herramientas, pero para redactar no hace falta.

Se activa con ASISTENTE_MODEL_REDACTOR_OLLAMA (ej. "gemma3:12b"). Vacío = desactivado: el reporte
lo escribe el modelo principal. Si el redactor falla (Ollama apagado, modelo no descargado), se usa
la respuesta del modelo principal en vez de dejar al usuario sin reporte.
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


def modelo_configurado() -> str:
    return os.getenv("ASISTENTE_MODEL_REDACTOR_OLLAMA", "").strip()


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


def redactar(toolkit: Toolkit, reporte_data: dict) -> str | None:
    """Narrativa del reporte escrita por el redactor, o None si no hay redactor o si falló."""
    modelo = modelo_configurado()
    if not modelo:
        return None
    sistema = f"{toolkit.contexto_redactor} {SISTEMA_BASE}".strip()
    try:
        r = _cliente().chat(
            model=modelo,
            keep_alive=KEEP_ALIVE,
            options={"temperature": 0.1, "num_predict": -1},
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": entrada_redactor(toolkit, reporte_data)},
            ],
        )
        return (r["message"]["content"] or "").strip() or None
    except Exception as e:
        print(f"ADVERTENCIA: el modelo redactor '{modelo}' falló ({e}); "
              "se usa la respuesta del modelo principal.")
        return None
