"""
Pruebas de humo del núcleo. No necesitan pytest ni conexión a ningún modelo:

    python tests/test_smoke.py

Cada prueba cubre algo que en algún momento falló de verdad al construir el
asistente (ver docs/COMO_SE_CONSTRUYO.md).
"""
import os
import sys
import traceback

os.environ["ASISTENTE_ACTIVO"] = "1"   # el asistente viene apagado por defecto; las pruebas lo necesitan prendido

from fastapi import FastAPI
from fastapi.testclient import TestClient

from asistente_core import (
    Toolkit, construir_instrucciones_reporte, construir_system_prompt, crear_router, llm, redactor,
)
from asistente_core.costos import costo_usd
from asistente_core.informe import construir_reporte_html
from asistente_core.limites import Limites
from asistente_core.providers import anthropic_provider


def _schema(nombre, **props):
    return {"name": nombre, "description": nombre,
            "input_schema": {"type": "object", "properties": props}}


def _toolkit(**kw):
    def suma(request, a: int = 0, b: int = 0, flag: bool = False):
        return {"suma": a + b, "flag": flag}

    schemas = [_schema("suma", a={"type": "integer"}, b={"type": "integer"}, flag={"type": "boolean"})]
    return Toolkit(schemas=schemas, functions={"suma": suma}, system_prompt="x", **kw)


def test_toolkit_detecta_nombres_que_no_cuadran():
    try:
        Toolkit(schemas=[_schema("a")], functions={"b": lambda r: {}}, system_prompt="x")
    except ValueError as e:
        assert "a" in str(e) and "b" in str(e)
    else:
        raise AssertionError("debió lanzar ValueError")


def test_coercion_de_tipos_del_modelo():
    # Un modelo local mandó excluir_gc="false" (texto) y Python lo trató como verdadero.
    r = _toolkit().ejecutar("suma", {"a": "2", "b": "3.0", "flag": "false"}, request=None)
    assert r == {"suma": 5, "flag": False}, r


def test_null_del_modelo_usa_el_valor_por_defecto():
    # Bug real: el modelo mandó limit=null y la búsqueda de cuentas tronó con int(None).
    r = _toolkit().ejecutar("suma", {"a": None, "b": "null", "flag": ""}, request=None)
    assert r == {"suma": 0, "flag": False}, r


def test_parametro_inexistente_lista_los_validos_y_pide_reintentar():
    # Bug real: el modelo mandó excluir_gc a una herramienta que no lo acepta; el error no decía
    # cómo corregirlo y el modelo lo explicó como "no puedo por privacidad".
    tk = _toolkit()
    r = tk.ejecutar("suma", {"a": 1, "excluir_gc": False}, request=None)
    assert "excluir_gc" in r["error"] and "['a', 'b', 'flag']" in r["error"]
    assert "Vuelve a llamar" in tk.para_llm(r)["instruccion"]


REPORTE_DE_PRUEBA = {
    "titulo": "T", "kpis": {"Total": 5}, "hechos_clave": ["Hay 5 cuentas."],
    "chart_specs": {"c": {"traces": [{"x": ["SECRETO_GRAFICA"]}], "layout": {}}},
    "tabla_detalle": [{"monto": 276224}],
}


def test_el_redactor_solo_recibe_datos_agregados():
    tk = _toolkit(instrucciones_reporte="REDACTA ASÍ")
    entrada = redactor.entrada_redactor(tk, REPORTE_DE_PRUEBA)
    assert "REDACTA ASÍ" in entrada and "Hay 5 cuentas." in entrada
    assert "SECRETO_GRAFICA" not in entrada, "las gráficas no deben llegar al redactor"
    assert "276224" not in entrada, "la tabla de cuentas no debe llegar al redactor"


class _ClienteFalso:
    def __init__(self, texto=None, falla=False):
        self.texto, self.falla, self.llamadas = texto, falla, []

    def chat(self, **kw):
        self.llamadas.append(kw)
        if self.falla:
            raise ConnectionError("Ollama apagado")
        return {"message": {"content": self.texto}}


def _con_redactor(cliente, modelo="gemma-falso"):
    import os
    original = (redactor._cliente, os.environ.get("ASISTENTE_MODEL_REDACTOR_OLLAMA"), os.environ.get("ASISTENTE_PROVIDER"))
    os.environ["ASISTENTE_PROVIDER"] = "ollama"
    redactor._cliente = lambda: cliente
    if modelo is None:
        os.environ.pop("ASISTENTE_MODEL_REDACTOR_OLLAMA", None)
    else:
        os.environ["ASISTENTE_MODEL_REDACTOR_OLLAMA"] = modelo

    def restaurar():
        redactor._cliente = original[0]
        if original[2] is None:
            os.environ.pop("ASISTENTE_PROVIDER", None)
        else:
            os.environ["ASISTENTE_PROVIDER"] = original[2]
        if original[1] is None:
            os.environ.pop("ASISTENTE_MODEL_REDACTOR_OLLAMA", None)
        else:
            os.environ["ASISTENTE_MODEL_REDACTOR_OLLAMA"] = original[1]
    return restaurar


def test_redactor_apagado_por_defecto_y_si_falla_no_truena():
    tk = _toolkit(contexto_redactor="Contexto del dominio.")
    restaurar = _con_redactor(_ClienteFalso("x"), modelo=None)
    try:
        assert redactor.redactar(tk, REPORTE_DE_PRUEBA) is None, "sin variable de entorno está apagado"
    finally:
        restaurar()
    restaurar = _con_redactor(_ClienteFalso(falla=True))
    try:
        assert redactor.redactar(tk, REPORTE_DE_PRUEBA) is None, "si Ollama falla se usa el modelo principal"
    finally:
        restaurar()
    cliente = _ClienteFalso("Texto del redactor.")
    restaurar = _con_redactor(cliente)
    try:
        assert redactor.redactar(tk, REPORTE_DE_PRUEBA) == "Texto del redactor."
    finally:
        restaurar()
    llamada = cliente.llamadas[0]
    assert llamada["model"] == "gemma-falso" and llamada["keep_alive"] == redactor.KEEP_ALIVE
    assert llamada["messages"][0]["content"].startswith("Contexto del dominio.")


def test_router_usa_el_texto_del_redactor_tambien_en_el_historial():
    respuesta = {
        "reply": "Texto corto del modelo principal.", "chart_spec": None, "tabla": None, "tool_trace": [],
        "historial": [{"role": "user", "content": "hola"},
                      {"role": "assistant", "content": "Texto corto del modelo principal."}],
        "reporte_data": dict(REPORTE_DE_PRUEBA),
    }
    restaurar = _con_redactor(_ClienteFalso("## Resumen\nTexto largo del redactor."))
    cliente, original = _app_con_respuesta(respuesta)
    try:
        cuerpo = cliente.post("/asistente/chat", json={"mensaje": "reporte", "historial": []}).json()
    finally:
        llm.responder = original
        restaurar()
    assert cuerpo["reply"] == "## Resumen\nTexto largo del redactor."
    assert "Texto largo del redactor." in cuerpo["reporte_html"]
    assert cuerpo["historial"][-1]["content"] == "## Resumen\nTexto largo del redactor."


def test_router_si_el_redactor_falla_conserva_la_respuesta_principal():
    respuesta = {
        "reply": "Texto del modelo principal.", "chart_spec": None, "tabla": None, "tool_trace": [],
        "historial": [{"role": "assistant", "content": "Texto del modelo principal."}],
        "reporte_data": dict(REPORTE_DE_PRUEBA),
    }
    restaurar = _con_redactor(_ClienteFalso(falla=True))
    cliente, original = _app_con_respuesta(respuesta)
    try:
        cuerpo = cliente.post("/asistente/chat", json={"mensaje": "reporte", "historial": []}).json()
    finally:
        llm.responder = original
        restaurar()
    assert cuerpo["reply"] == "Texto del modelo principal." and "reporte_html" in cuerpo


def test_un_error_le_indica_al_modelo_que_no_invente():
    # Bug real: tras un error de herramienta, el modelo inventó tablas y cifras completas.
    tk = _toolkit()
    error = {"error": "no se encontró"}
    visto = tk.para_llm(error)
    assert "No inventes" in visto["instruccion"] and visto["error"] == "no se encontró"
    assert "instruccion" not in error, "no debe mutar el original"


def test_errores_de_herramienta_no_truenan():
    tk = _toolkit()
    assert "desconocida" in tk.ejecutar("nada", {}, None)["error"]
    assert "no acepta" in tk.ejecutar("suma", {"zzz": 1}, None)["error"]


def test_para_llm_oculta_tabla_solo_en_reportes():
    tk = _toolkit()
    reporte = {"chart_specs": {}, "tabla_detalle": [{"monto": 276224}], "hechos_clave": ["x"]}
    visto = tk.para_llm(reporte)
    assert isinstance(visto["tabla_detalle"], str) and "276224" not in visto["tabla_detalle"]
    assert visto["hechos_clave"] == ["x"]
    assert reporte["tabla_detalle"] == [{"monto": 276224}], "no debe mutar el original"
    consulta = {"cuentas": [{"monto": 1}]}
    assert tk.para_llm(consulta) is consulta


def test_prompt_incluye_reglas_y_solo_un_puntero_al_reporte_largo():
    secciones = ["## Resumen ejecutivo", "## Detalle (solo si aplica)"]
    p = construir_system_prompt(
        "Eres el asistente de X.", reglas_propias=["- Regla propia."],
        reporte_corto="Reportes cortos: ...", secciones_reporte_extenso=secciones,
    )
    for esperado in ("Eres el asistente de X.", "Nunca inventes cifras", "- Regla propia.",
                     "Reportes cortos", "reporte_extenso", "ÚNICAMENTE en un reporte extenso"):
        assert esperado in p, esperado
    # Bug real: con el bloque largo dentro del prompt, el modelo contagiaba el formato de
    # reporte a todas las respuestas. Las secciones NO deben estar en el prompt general.
    assert "## Detalle (solo si aplica)" not in p and "hechos_clave" not in p
    assert "reporte_extenso" not in construir_system_prompt("Hola.")


def test_instrucciones_del_reporte_tienen_las_secciones_y_las_reglas():
    t = construir_instrucciones_reporte(["## Resumen ejecutivo", "## Detalle (solo si aplica)"])
    for esperado in ("## Detalle (solo si aplica)", 'empieza directo con "## Resumen ejecutivo"',
                     "hechos_clave", "tabla_detalle"):
        assert esperado in t, esperado


def test_instrucciones_llegan_solo_con_el_resultado_de_un_reporte():
    tk = _toolkit(instrucciones_reporte="REDACTA ASÍ")
    reporte = {"chart_specs": {}, "hechos_clave": ["x"]}
    assert tk.para_llm(reporte)["instrucciones_de_redaccion"] == "REDACTA ASÍ"
    assert "instrucciones_de_redaccion" not in reporte, "no debe mutar el original"
    consulta = {"cuentas": [1]}
    assert tk.para_llm(consulta) is consulta


def test_informe_html_completo_y_bien_cerrado():
    chart = {"traces": [{"type": "bar", "x": ["a"], "y": [1]}], "layout": {"title": "t</script>x"}}
    html = construir_reporte_html(
        titulo="Reporte de la colonia X", dataset="DS", narrativa="**Reporte de la colonia X**\n\n## Resumen\nTexto.",
        kpis={"Total": 5}, chart_specs={"uno": chart, "dos": chart},
        tabla=[{"nis": 1, "monto": 2}], titulo_tabla="Cuentas destacadas",
        nombre_app="Adeudos", nota="Nota propia.",
    )
    # Bug real: escapar mal </script> se tragaba la 2a gráfica, la tabla y el cierre.
    assert html.count("<script") == html.count("</script>") == 3
    assert 'id="chart-0"' in html and 'id="chart-1"' in html
    assert "<h2>Cuentas destacadas</h2>" in html and html.rstrip().endswith("</html>")
    assert "<h2>Reporte de la colonia X</h2>" not in html, "título duplicado"
    assert "Dataset: DS" in html and "Adeudos" in html and "Nota propia." in html


def _app_con_respuesta(respuesta):
    original = llm.responder
    llm.responder = lambda *a, **k: respuesta
    app = FastAPI()
    app.include_router(crear_router(_toolkit(nombre_app="App"), etiqueta_dataset=lambda r: "DS"))
    return TestClient(app), original


def test_router_arma_reporte_html_y_sirve_el_boton():
    respuesta = {
        "reply": "## Resumen\nTexto.", "chart_spec": None, "tabla": None, "historial": [], "tool_trace": [],
        "reporte_data": {"titulo": "T", "kpis": {"a": 1}, "tabla_detalle": [{"x": 1}],
                         "titulo_tabla": "Detalle X", "chart_specs": {"c": {"traces": [], "layout": {}}}},
    }
    cliente, original = _app_con_respuesta(respuesta)
    try:
        r = cliente.post("/asistente/chat", json={"mensaje": "hola", "historial": []})
        assert r.status_code == 200
        cuerpo = r.json()
        assert "reporte_data" not in cuerpo and "<h2>Detalle X</h2>" in cuerpo["reporte_html"]
        js = cliente.get("/asistente/asistente.js")
        assert js.status_code == 200 and "javascript" in js.headers["content-type"]
        assert "/asistente/chat" in js.text
    finally:
        llm.responder = original


def test_router_sin_reporte_no_agrega_html():
    respuesta = {"reply": "hola", "chart_spec": None, "tabla": None, "reporte_data": None,
                 "historial": [], "tool_trace": []}
    cliente, original = _app_con_respuesta(respuesta)
    try:
        cuerpo = cliente.post("/asistente/chat", json={"mensaje": "hola"}).json()
        assert "reporte_html" not in cuerpo and cuerpo["reply"] == "hola"
    finally:
        llm.responder = original


def test_apagado_por_defecto_no_expone_ninguna_ruta():
    anterior = os.environ.pop("ASISTENTE_ACTIVO")
    try:
        app = FastAPI()
        app.include_router(crear_router(_toolkit(nombre_app="App")))
        cliente = TestClient(app)
        assert cliente.get("/asistente/asistente.js").status_code == 404
        assert cliente.post("/asistente/chat", json={"mensaje": "hola"}).status_code == 404
    finally:
        os.environ["ASISTENTE_ACTIVO"] = anterior


def test_costo_aproximado_por_modelo():
    assert abs(costo_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) - 12.0) < 1e-9
    assert abs(costo_usd("claude-haiku-5-5", 10_000, 1_000) - 0.0015) < 1e-9
    assert costo_usd("modelo-desconocido", 1000, 1000) is None


def test_limite_diario_por_usuario_y_tope_de_gasto():
    os.environ["ASISTENTE_LIMITE_USUARIO_DIA"] = "2"
    os.environ["ASISTENTE_TOPE_DIARIO_USD"] = "1"
    try:
        lim = Limites()
        assert lim.revisar("ana") is None and lim.revisar("ana") is None
        assert "límite" in lim.revisar("ana")          # la tercera de ana se bloquea...
        assert lim.revisar("luis") is None             # ...pero luis puede seguir
        lim.registrar_gasto(1.5)
        assert "límite de uso" in lim.revisar("luis")  # y el tope de gasto bloquea a todos
        os.environ["ASISTENTE_LIMITE_USUARIO_DIA"] = "0"
        os.environ["ASISTENTE_TOPE_DIARIO_USD"] = "0"
        assert Limites().revisar("ana") is None        # 0 = sin tope
    finally:
        del os.environ["ASISTENTE_LIMITE_USUARIO_DIA"], os.environ["ASISTENTE_TOPE_DIARIO_USD"]


def test_router_bloquea_al_pasar_el_limite_y_no_truena_si_el_modelo_falla():
    from asistente_core import router as modulo_router
    original, lim_original = llm.responder, modulo_router.limites
    try:
        def falla(*a, **k):
            raise RuntimeError("sin saldo")
        llm.responder = falla
        modulo_router.limites = Limites()
        app = FastAPI()
        app.include_router(crear_router(_toolkit(nombre_app="App")))
        c = TestClient(app)
        r = c.post("/asistente/chat", json={"mensaje": "hola"})
        assert r.status_code == 200 and "No pude consultar" in r.json()["reply"]
        assert "sin saldo" not in r.text               # el detalle técnico no llega al usuario
        os.environ["ASISTENTE_LIMITE_USUARIO_DIA"] = "1"
        modulo_router.limites = Limites()
        c.post("/asistente/chat", json={"mensaje": "uno"})
        assert "límite" in c.post("/asistente/chat", json={"mensaje": "dos"}).json()["reply"]
    finally:
        os.environ.pop("ASISTENTE_LIMITE_USUARIO_DIA", None)
        llm.responder, modulo_router.limites = original, lim_original


def test_el_historial_no_lleva_bloques_de_razonamiento():
    mensajes = [{"role": "user", "content": "hola"},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                                  {"type": "text", "text": "hola"}]}]
    limpio = anthropic_provider._sin_pensamiento(mensajes)
    assert [b["type"] for b in limpio[1]["content"]] == ["text"] and limpio[0] == mensajes[0]


def test_redactor_con_claude_usa_su_variable_y_reporta_el_costo():
    from types import SimpleNamespace
    llamadas = []

    class _Mensajes:
        def create(self, **kw):
            llamadas.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Texto de Claude.")],
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=2000))

    anterior = (anthropic_provider._get_client, os.environ.get("ASISTENTE_PROVIDER"),
                os.environ.get("ASISTENTE_MODEL_REDACTOR"))
    anthropic_provider._get_client = lambda: SimpleNamespace(messages=_Mensajes())
    os.environ["ASISTENTE_PROVIDER"] = "anthropic"
    os.environ["ASISTENTE_MODEL_REDACTOR"] = "claude-sonnet-5-5"
    try:
        texto, uso = redactor.redactar_con_uso(_toolkit(contexto_redactor="Contexto."), REPORTE_DE_PRUEBA)
        assert texto == "Texto de Claude." and llamadas[0]["model"] == "claude-sonnet-5-5"
        assert llamadas[0]["system"].startswith("Contexto.") and "tools" not in llamadas[0]
        assert abs(uso["costo_usd"] - 0.022) < 1e-9          # 1000*2/1e6 + 2000*10/1e6
    finally:
        anthropic_provider._get_client = anterior[0]
        for k, v in (("ASISTENTE_PROVIDER", anterior[1]), ("ASISTENTE_MODEL_REDACTOR", anterior[2])):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_el_usuario_para_los_limites_sale_de_la_sesion_o_del_jwt():
    from types import SimpleNamespace
    from asistente_core.router import _usuario
    cliente = SimpleNamespace(host="9.9.9.9")
    jwt = SimpleNamespace(state=SimpleNamespace(user={"sub": "ana"}), client=cliente)
    sesion = SimpleNamespace(state=SimpleNamespace(), session={"user": {"user": "luis", "name": "Luis"}}, client=cliente)
    nada = SimpleNamespace(state=SimpleNamespace(), client=cliente)          # sin sesión: cae a la IP
    jwt_en_session = SimpleNamespace(state=SimpleNamespace(session={"sub": "marta"}), client=cliente)
    assert (_usuario(jwt), _usuario(sesion), _usuario(nada), _usuario(jwt_en_session)) == ("ana", "luis", "9.9.9.9", "marta")


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok     {nombre}")
            except Exception:
                fallos += 1
                print(f"FALLA  {nombre}")
                traceback.print_exc()
    print("\nTodo bien." if not fallos else f"\n{fallos} prueba(s) fallaron.")
    sys.exit(1 if fallos else 0)
