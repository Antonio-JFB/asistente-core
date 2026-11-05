"""Adaptador de FastAPI: traduce la petición HTTP y llama a `chat.procesar_chat`."""
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .chat import procesar_chat, script_con_config, usuario_de as _usuario, respuesta_simple as _respuesta_simple  # noqa: F401
from .comentarios import procesar_comentario
from .config import asistente_activo
from .limites import limites  # noqa: F401  (los tests reemplazan router.limites)
from .toolkit import Toolkit


class ChatRequest(BaseModel):
    mensaje: str
    historial: list[dict] = []


class ComentarioRequest(BaseModel):
    categoria: str = "otro"
    texto: str = Field(max_length=5000)   # el límite real (1000) lo aplica procesar_comentario con un mensaje claro


def crear_router(
    toolkit: Toolkit,
    etiqueta_dataset: Callable[[Request], str] | None = None,
) -> APIRouter:
    """Crea el router del asistente para UN dashboard.

    Expone tres rutas: POST /asistente/chat, POST /asistente/comentarios (el formulario de comentarios
    del chat) y GET /asistente/asistente.js (el botón de chat, que sirve el propio paquete para no copiarlo a cada dashboard).
    Hereda la autenticación del dashboard (sus middlewares) y no define la suya.

    etiqueta_dataset: opcional; recibe el request y regresa el nombre del conjunto
        de datos activo para mostrarlo en el encabezado de los reportes.
    """
    router = APIRouter(prefix="/asistente", tags=["asistente"])
    if not asistente_activo():
        print("INFO: asistente apagado (ASISTENTE_ACTIVO no está en 1); no se expone ninguna ruta /asistente.")
        return router

    @router.get("/asistente.js", include_in_schema=False)
    def script():
        return Response(script_con_config(toolkit), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    # `def` y no `async def` a propósito: la llamada al modelo es bloqueante (de segundos a minutos).
    # En una función async congelaría todo el dashboard mientras responde; en una función normal
    # FastAPI la corre en otro hilo y las demás páginas siguen atendiéndose.
    @router.post("/chat")
    def chat(request: Request, payload: ChatRequest):
        return procesar_chat(toolkit, payload.mensaje, payload.historial, request, etiqueta_dataset)

    @router.post("/comentarios")
    def comentarios(request: Request, payload: ComentarioRequest):
        quien = toolkit.usuario_de or _usuario
        codigo, cuerpo = procesar_comentario(toolkit, payload.categoria, payload.texto, quien(request))
        return JSONResponse(cuerpo, status_code=codigo)

    return router
