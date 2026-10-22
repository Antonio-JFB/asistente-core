from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import llm, redactor
from .informe import construir_reporte_html
from .toolkit import Toolkit

_JS = Path(__file__).parent / "static" / "asistente.js"


def _reemplazar_ultima_respuesta(historial, texto):
    """Que el historial que viaja de vuelta al navegador tenga el texto que el usuario sí vio
    (el del redactor), para que las preguntas de seguimiento partan de ese reporte."""
    if not historial or historial[-1].get("role") != "assistant":
        return
    if isinstance(historial[-1].get("content"), list):
        historial[-1]["content"] = [{"type": "text", "text": texto}]
    else:
        historial[-1]["content"] = texto


class ChatRequest(BaseModel):
    mensaje: str
    historial: list[dict] = []


def crear_router(
    toolkit: Toolkit,
    etiqueta_dataset: Callable[[Request], str] | None = None,
) -> APIRouter:
    """Crea el router del asistente para UN dashboard.

    Expone dos rutas: POST /asistente/chat y GET /asistente/asistente.js (el botón
    de chat, que sirve el propio paquete para no copiarlo a cada dashboard).
    Hereda la autenticación del dashboard (sus middlewares) y no define la suya.

    etiqueta_dataset: opcional; recibe el request y regresa el nombre del conjunto
        de datos activo para mostrarlo en el encabezado de los reportes.
    """
    router = APIRouter(prefix="/asistente", tags=["asistente"])

    @router.get("/asistente.js", include_in_schema=False)
    def script():
        return FileResponse(_JS, media_type="application/javascript")

    # `def` y no `async def` a propósito: la llamada al modelo es bloqueante (de
    # segundos a minutos con un modelo local). En una función async congelaría
    # todo el dashboard mientras responde; en una función normal FastAPI la corre
    # en otro hilo y las demás páginas siguen atendiéndose.
    @router.post("/chat")
    def chat(request: Request, payload: ChatRequest):
        resultado = llm.responder(payload.mensaje, payload.historial, request, toolkit)

        # Si se usó el reporte extenso, aquí se arma la página completa (una sola
        # vez, no en cada proveedor) con la narrativa del modelo + los datos reales.
        reporte_data = resultado.pop("reporte_data", None)
        if reporte_data and "error" not in reporte_data:
            texto = redactor.redactar(toolkit, reporte_data)   # None si no hay redactor o si falló
            if texto:
                resultado["reply"] = texto
                _reemplazar_ultima_respuesta(resultado.get("historial"), texto)
            resultado["reporte_html"] = construir_reporte_html(
                titulo=reporte_data.get("titulo", "Reporte"),
                dataset=etiqueta_dataset(request) if etiqueta_dataset else "",
                narrativa=resultado.get("reply", ""),
                kpis=reporte_data.get("kpis", {}),
                chart_specs=reporte_data.get("chart_specs", {}),
                tabla=reporte_data.get("tabla_detalle"),
                titulo_tabla=reporte_data.get("titulo_tabla", "Detalle"),
                nombre_app=toolkit.nombre_app,
                nota=toolkit.nota_reporte,
            )
        return resultado

    return router
