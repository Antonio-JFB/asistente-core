"""
Lógica del chat, independiente del framework web (FastAPI, Django...).

`procesar_chat` recibe la pregunta y devuelve el diccionario de respuesta; los adaptadores
(`router.py` para FastAPI, `django_vistas.py` para Django) solo traducen la petición HTTP.
Así las reglas (atajos locales, datos bloqueados, límites de uso, costos, redactor, reporte HTML)
son idénticas en todos los dashboards.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from . import llm, redactor
from .informe import construir_reporte_html
from .limites import limites
from .toolkit import Toolkit

JS = Path(__file__).parent / "static" / "asistente.js"


def script_con_config(toolkit: Toolkit) -> str:
    """El botón de chat con la configuración del dashboard (saludo) antepuesta, sin una petición extra."""
    config = "window.ASISTENTE_CONFIG = " + json.dumps({"saludo": toolkit.saludo}, ensure_ascii=False) + ";\n"
    return config + JS.read_text(encoding="utf-8")


def reemplazar_ultima_respuesta(historial, texto):
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


def usuario_de(request) -> str:
    """Quién consulta, para el límite diario. Reconoce, en orden: `request.state.user` / `request.state.session`
    (claims del JWT, FastAPI), `request.user` (Django), `request.session["user"]` (Starlette o Django) y, si no hay
    nada, la IP. Un dashboard con otra forma de identificar puede dar `Toolkit.usuario_de`."""
    estado = getattr(request, "state", None)
    for atributo in ("user", "session"):
        nombre = _nombre_de(getattr(estado, atributo, None)) if estado is not None else None
        if nombre:
            return nombre
    try:
        usuario = getattr(request, "user", None)         # Django (en Starlette falla si no hay AuthenticationMiddleware)
    except Exception:
        usuario = None
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        nombre = _nombre_de(getattr(usuario, "get_username", lambda: None)())
        if nombre:
            return nombre
    try:
        nombre = _nombre_de(request.session.get("user"))   # falla si no hay sesión configurada
    except Exception:
        nombre = None
    if nombre:
        return nombre
    cliente = getattr(request, "client", None)           # FastAPI
    if cliente is not None and getattr(cliente, "host", None):
        return cliente.host
    meta = getattr(request, "META", None)                # Django
    return (meta.get("REMOTE_ADDR") if meta else None) or "desconocido"


def respuesta_simple(texto: str, historial: list[dict]) -> dict:
    return {"reply": texto, "chart_spec": None, "tabla": None, "historial": historial, "tool_trace": []}


def procesar_chat(
    toolkit: Toolkit,
    mensaje: str,
    historial: list[dict],
    request,
    etiqueta_dataset: Callable[[object], str] | None = None,
) -> dict:
    """Atiende una pregunta del chat y devuelve la respuesta lista para serializar a JSON."""
    quien = toolkit.usuario_de or usuario_de

    encontrado = toolkit.buscar_atajo(mensaje)
    if encontrado:   # se contesta aquí, sin enviar nada al modelo
        atajo, valor = encontrado
        usuario = quien(request)
        bloqueo = limites.revisar(usuario)   # cuenta para el límite diario: evita recorrer datos uno por uno
        if bloqueo:
            return respuesta_simple(bloqueo, historial)
        try:
            texto = atajo.funcion(request, valor)
        except Exception as e:
            print(f"[asistente] ERROR en el atajo '{atajo.nombre}': {type(e).__name__}", flush=True)
            texto = "No pude consultar ese dato en este momento. Intenta de nuevo en unos minutos."
        print(f"[asistente] usuario={usuario} atajo={atajo.nombre} (sin modelo)", flush=True)   # nunca el dato
        return respuesta_simple(texto, historial)

    dato = toolkit.dato_bloqueado(mensaje)
    if dato:   # antes de gastar una consulta del límite y, sobre todo, antes de enviar nada al modelo
        return respuesta_simple(
            f"Tu pregunta incluye {dato}, y por privacidad no la envío al modelo. Este asistente solo trabaja con "
            "cifras agregadas: vuelve a preguntar sin ese dato.", historial)

    usuario = quien(request)
    bloqueo = limites.revisar(usuario)
    if bloqueo:
        return respuesta_simple(bloqueo, historial)
    try:
        resultado = llm.responder(mensaje, historial, request, toolkit)
    except Exception as e:   # sin saldo, sin red, llave inválida...: el detalle va al registro, no al usuario
        print(f"[asistente] ERROR al consultar el modelo: {type(e).__name__}: {e}", flush=True)
        return respuesta_simple("No pude consultar al asistente en este momento. Intenta de nuevo en unos minutos.", historial)
    uso = resultado.get("uso")
    if uso:
        limites.registrar_gasto(uso.get("costo_usd"))
        print(f"[asistente] usuario={usuario} modelo={uso['modelo']} llamadas={uso['llamadas']} "
              f"tokens_in={uso['tokens_entrada']} tokens_out={uso['tokens_salida']} "
              f"costo≈${uso['costo_usd']:.4f} gasto_hoy≈${limites.gasto_hoy:.2f} "
              f"herramientas={[t['tool'] for t in resultado.get('tool_trace', [])]}", flush=True)

    # Si se usó el reporte extenso, aquí se arma la página completa (una sola vez, no en cada proveedor)
    # con la narrativa del modelo + los datos reales.
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
            reemplazar_ultima_respuesta(resultado.get("historial"), texto)
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
