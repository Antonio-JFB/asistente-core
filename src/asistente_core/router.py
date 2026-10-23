import json
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from . import llm, redactor
from .config import asistente_activo
from .informe import construir_reporte_html
from .limites import limites
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


def _nombre_de(dato) -> str | None:
    if isinstance(dato, dict):
        for campo in ("sub", "email", "username", "user", "user_id", "uid"):
            if dato.get(campo):
                return str(dato[campo])
        return None
    return str(dato) if dato else None


def _usuario(request: Request) -> str:
    """Quién consulta, para el límite diario: el usuario de la sesión del dashboard (JWT en
    `request.state.user` o cookie de sesión de Starlette en `request.session`) o, si no hay, la IP."""
    for atributo in ("user", "session"):          # request.state.user / request.state.session (claims del JWT)
        nombre = _nombre_de(getattr(request.state, atributo, None))
        if nombre:
            return nombre
    try:
        nombre = _nombre_de(request.session.get("user"))   # falla si la app no usa SessionMiddleware
    except Exception:
        nombre = None
    if nombre:
        return nombre
    return request.client.host if request.client else "desconocido"


def _respuesta_simple(texto: str, historial: list[dict]) -> dict:
    return {"reply": texto, "chart_spec": None, "tabla": None, "historial": historial, "tool_trace": []}


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
    if not asistente_activo():
        print("INFO: asistente apagado (ASISTENTE_ACTIVO no está en 1); no se expone ninguna ruta /asistente.")
        return router

    @router.get("/asistente.js", include_in_schema=False)
    def script():
        # La configuración del dashboard (saludo) se antepone al script, sin una petición extra.
        config = "window.ASISTENTE_CONFIG = " + json.dumps({"saludo": toolkit.saludo}, ensure_ascii=False) + ";\n"
        return Response(config + _JS.read_text(encoding="utf-8"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    # `def` y no `async def` a propósito: la llamada al modelo es bloqueante (de
    # segundos a minutos con un modelo local). En una función async congelaría
    # todo el dashboard mientras responde; en una función normal FastAPI la corre
    # en otro hilo y las demás páginas siguen atendiéndose.
    @router.post("/chat")
    def chat(request: Request, payload: ChatRequest):
        encontrado = toolkit.buscar_atajo(payload.mensaje)
        if encontrado:   # se contesta aquí, sin enviar nada al modelo
            atajo, valor = encontrado
            usuario = _usuario(request)
            bloqueo = limites.revisar(usuario)   # cuenta para el límite diario: evita recorrer datos uno por uno
            if bloqueo:
                return _respuesta_simple(bloqueo, payload.historial)
            try:
                texto = atajo.funcion(request, valor)
            except Exception as e:
                print(f"[asistente] ERROR en el atajo '{atajo.nombre}': {type(e).__name__}", flush=True)
                texto = "No pude consultar ese dato en este momento. Intenta de nuevo en unos minutos."
            print(f"[asistente] usuario={usuario} atajo={atajo.nombre} (sin modelo)", flush=True)   # nunca el dato
            return _respuesta_simple(texto, payload.historial)
        dato = toolkit.dato_bloqueado(payload.mensaje)
        if dato:   # antes de gastar una consulta del límite y, sobre todo, antes de enviar nada al modelo
            return _respuesta_simple(
                f"Tu pregunta incluye {dato}, y por privacidad no la envío al modelo. Este asistente solo trabaja con "
                "cifras agregadas: vuelve a preguntar sin ese dato.", payload.historial)
        usuario = _usuario(request)
        bloqueo = limites.revisar(usuario)
        if bloqueo:
            return _respuesta_simple(bloqueo, payload.historial)
        try:
            resultado = llm.responder(payload.mensaje, payload.historial, request, toolkit)
        except Exception as e:   # sin saldo, sin red, llave inválida...: el detalle va al registro, no al usuario
            print(f"[asistente] ERROR al consultar el modelo: {type(e).__name__}: {e}", flush=True)
            return _respuesta_simple("No pude consultar al asistente en este momento. Intenta de nuevo en unos minutos.",
                                     payload.historial)
        uso = resultado.get("uso")
        if uso:
            limites.registrar_gasto(uso.get("costo_usd"))
            print(f"[asistente] usuario={usuario} modelo={uso['modelo']} llamadas={uso['llamadas']} "
                  f"tokens_in={uso['tokens_entrada']} tokens_out={uso['tokens_salida']} "
                  f"costo≈${uso['costo_usd']:.4f} gasto_hoy≈${limites.gasto_hoy:.2f} "
                  f"herramientas={[t['tool'] for t in resultado.get('tool_trace', [])]}", flush=True)

        # Si se usó el reporte extenso, aquí se arma la página completa (una sola
        # vez, no en cada proveedor) con la narrativa del modelo + los datos reales.
        reporte_data = resultado.pop("reporte_data", None)
        if reporte_data and "error" not in reporte_data:
            texto, uso_redactor = redactor.redactar_con_uso(toolkit, reporte_data)   # None si no hay redactor o falló
            if uso_redactor:
                limites.registrar_gasto(uso_redactor["costo_usd"])
                print(f"[asistente] redactor modelo={uso_redactor['modelo']} tokens_in={uso_redactor['tokens_entrada']} "
                      f"tokens_out={uso_redactor['tokens_salida']} costo≈${uso_redactor['costo_usd']:.4f} "
                      f"gasto_hoy≈${limites.gasto_hoy:.2f}", flush=True)
                if resultado.get("uso"):
                    resultado["uso"] = {**resultado["uso"], "costo_usd": resultado["uso"]["costo_usd"] + uso_redactor["costo_usd"],
                                        "tokens_salida": resultado["uso"]["tokens_salida"] + uso_redactor["tokens_salida"],
                                        "tokens_entrada": resultado["uso"]["tokens_entrada"] + uso_redactor["tokens_entrada"]}
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
