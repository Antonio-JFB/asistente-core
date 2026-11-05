"""
Comentarios de los usuarios sobre el asistente (el botón "Comentarios" del chat).

Solo se guarda lo que la persona escribe en el formulario, con quién y cuándo. NO se guardan sus preguntas ni
las respuestas del chat: la bitácora del asistente tampoco lleva su texto, y esto no lo cambia.

Cada comentario es una línea JSON en un archivo del servidor (`ASISTENTE_COMENTARIOS_ARCHIVO`, por defecto
`asistente_comentarios.jsonl` en la carpeta donde corre el dashboard). Ese archivo debe quedar fuera del repositorio.
Para leerlos en Excel:

    python -m asistente_core.comentarios exportar asistente_comentarios.jsonl comentarios.csv

Variables de entorno:
  ASISTENTE_COMENTARIOS_ARCHIVO     dónde se guardan (default: asistente_comentarios.jsonl)
  ASISTENTE_LIMITE_COMENTARIOS_DIA  comentarios por persona por día (default 10; 0 = sin límite)
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import sys
import threading
from pathlib import Path

from .toolkit import Toolkit

MAX_CARACTERES = 1000
CATEGORIAS = {
    "error": "Una respuesta fue incorrecta",
    "sugerencia": "Sugerencia o idea",
    "otro": "Otro comentario",
}
CAMPOS = ["fecha", "usuario", "dashboard", "categoria", "comentario"]


def archivo_de_comentarios() -> Path:
    return Path(os.getenv("ASISTENTE_COMENTARIOS_ARCHIVO", "").strip() or "asistente_comentarios.jsonl")


def _limite_por_dia() -> int:
    try:
        return int(float(os.getenv("ASISTENTE_LIMITE_COMENTARIOS_DIA", "").strip() or 10))
    except ValueError:
        return 10


class _Contador:
    """Comentarios por persona en el día, en memoria (como `limites.Limites`: se reinicia al cambiar de día o al reiniciar)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._dia = datetime.date.today()
        self._cuenta: dict[str, int] = {}

    def permitir(self, usuario: str) -> bool:
        limite = _limite_por_dia()
        with self._lock:
            hoy = datetime.date.today()
            if hoy != self._dia:
                self._dia, self._cuenta = hoy, {}
            if limite and self._cuenta.get(usuario, 0) >= limite:
                return False
            self._cuenta[usuario] = self._cuenta.get(usuario, 0) + 1
            return True


contador = _Contador()
_escritura = threading.Lock()


def procesar_comentario(toolkit: Toolkit, categoria: str, texto: str, usuario: str) -> tuple[int, dict]:
    """Valida y guarda un comentario. Regresa (código HTTP, cuerpo JSON). Independiente del framework web."""
    texto = (texto or "").strip()
    if not texto:
        return 400, {"ok": False, "detail": "Escribe tu comentario antes de enviarlo."}
    if len(texto) > MAX_CARACTERES:
        return 400, {"ok": False, "detail": f"El comentario es demasiado largo (máximo {MAX_CARACTERES} caracteres)."}
    categoria = categoria if categoria in CATEGORIAS else "otro"

    # El mismo filtro de datos personales que el chat: un RFC, una CURP, un correo... no se guardan.
    dato = toolkit.dato_bloqueado(texto)
    if not dato:
        atajo = toolkit.buscar_atajo(texto)
        dato = atajo[0].nombre if atajo else None
    if dato:
        return 422, {"ok": False, "detail": f"Tu comentario incluye {dato}. Por privacidad no se guarda: quítalo y vuelve a enviarlo."}

    if not contador.permitir(usuario):
        return 429, {"ok": False, "detail": "Ya enviaste varios comentarios hoy. Gracias; puedes escribirnos de nuevo mañana."}

    registro = {
        "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
        "usuario": usuario,
        "dashboard": toolkit.nombre_app,
        "categoria": categoria,
        "comentario": texto,
    }
    try:
        ruta = archivo_de_comentarios()
        with _escritura:
            nuevo = not ruta.exists()
            with ruta.open("a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            if nuevo:
                try:
                    os.chmod(ruta, 0o600)   # solo quien administra el servidor lo lee (no aplica en Windows)
                except OSError:
                    pass
    except OSError as e:   # el texto del comentario nunca va al registro del servidor, solo el tipo de error
        print(f"[asistente] ERROR al guardar un comentario: {type(e).__name__}", flush=True)
        return 500, {"ok": False, "detail": "No pude guardar tu comentario en este momento. Intenta de nuevo en unos minutos."}
    print(f"[asistente] usuario={usuario} comentario guardado categoria={categoria} caracteres={len(texto)}", flush=True)
    return 200, {"ok": True}


def leer_comentarios(ruta: str | Path) -> list[dict]:
    filas = []
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        if linea.strip():
            try:
                filas.append(json.loads(linea))
            except ValueError:
                continue   # una línea dañada no impide leer las demás
    return filas


def exportar_csv(ruta: str | Path, salida: str | Path) -> int:
    """Pasa los comentarios a CSV (con BOM, para que Excel respete los acentos). Regresa cuántos exportó."""
    filas = leer_comentarios(ruta)
    with Path(salida).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return len(filas)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "exportar":
        print(f"{exportar_csv(sys.argv[2], sys.argv[3])} comentarios exportados a {sys.argv[3]}")
    else:
        print("Uso: python -m asistente_core.comentarios exportar <archivo.jsonl> <salida.csv>")
        sys.exit(2)
