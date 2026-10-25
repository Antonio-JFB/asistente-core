"""
Adaptador de Django: las mismas reglas del chat que en FastAPI (`chat.procesar_chat`), como vistas de Django.

Uso, en el `urls.py` del proyecto:

    from asistente_core.django_vistas import urlpatterns_asistente
    urlpatterns += urlpatterns_asistente(toolkit, etiqueta_dataset=lambda request: "Mi dashboard")

Con ASISTENTE_ACTIVO apagado la lista queda vacía: no hay rutas ni botón. Las dos rutas son
POST /asistente/chat y GET /asistente/asistente.js (el botón, que sirve el propio paquete).

Seguridad:
  * El chat exige el token CSRF de Django aunque el proyecto no tenga CsrfViewMiddleware: el botón lo manda en la
    cabecera X-CSRFToken (la vista del script deja la cookie con ensure_csrf_cookie).
  * Sin sesión válida responde 401 en JSON (no redirige al login: un fetch no podría leer esa página).
    Por defecto "con sesión" es `request.user.is_authenticated`; un dashboard con otro login (por ejemplo una
    cookie JWT compartida) da su propia función en `autenticado`.
  * Las llamadas al modelo son lentas (hasta ~1 minuto con un reporte largo): en gunicorn hay que subir
    `--timeout` (180) y conviene usar hilos (`--threads 4`); si no, el worker se reinicia a los 30 s.
"""
from __future__ import annotations

import json
from typing import Callable

from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie

from .chat import procesar_chat, script_con_config
from .config import asistente_activo
from .toolkit import Toolkit


def _autenticado_por_defecto(request) -> bool:
    return bool(getattr(getattr(request, "user", None), "is_authenticated", False))


def crear_vistas(
    toolkit: Toolkit,
    etiqueta_dataset: Callable[[object], str] | None = None,
    autenticado: Callable[[object], bool] | None = None,
):
    """(vista_chat, vista_script) para un dashboard."""
    esta_autenticado = autenticado or _autenticado_por_defecto

    @csrf_protect   # se aplica aunque el proyecto no tenga CsrfViewMiddleware (algunos no lo traen)
    def chat(request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not esta_autenticado(request):
            return JsonResponse({"detail": "No autenticado"}, status=401)
        try:
            cuerpo = json.loads(request.body or b"{}")
            mensaje = str(cuerpo.get("mensaje", ""))
            historial = cuerpo.get("historial") or []
            if not mensaje.strip() or not isinstance(historial, list):
                raise ValueError("mensaje vacío o historial inválido")
        except (ValueError, AttributeError):
            return JsonResponse({"detail": "Petición inválida"}, status=400)
        resultado = procesar_chat(toolkit, mensaje, historial, request, etiqueta_dataset)
        return JsonResponse(resultado, json_dumps_params={"ensure_ascii": False})

    @ensure_csrf_cookie
    def script(request):
        respuesta = HttpResponse(script_con_config(toolkit), content_type="application/javascript")
        respuesta["Cache-Control"] = "no-cache"
        return respuesta

    return chat, script


def urlpatterns_asistente(
    toolkit: Toolkit,
    etiqueta_dataset: Callable[[object], str] | None = None,
    autenticado: Callable[[object], bool] | None = None,
) -> list:
    """Rutas del asistente para `urls.py`. Vacío si el asistente está apagado."""
    if not asistente_activo():
        print("INFO: asistente apagado (ASISTENTE_ACTIVO no está en 1); no se expone ninguna ruta /asistente.")
        return []
    chat, script = crear_vistas(toolkit, etiqueta_dataset, autenticado)
    return [
        path("asistente/chat", chat, name="asistente_chat"),
        path("asistente/asistente.js", script, name="asistente_js"),
    ]
