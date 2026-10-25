"""
Pruebas del adaptador de Django. Necesitan Django instalado (si no está, se omiten):

    python tests/test_django.py
"""
import json
import os
import sys
from types import SimpleNamespace

os.environ["ASISTENTE_ACTIVO"] = "1"

try:
    import django
    from django.conf import settings
except ImportError:
    print("Django no está instalado: se omiten las pruebas del adaptador de Django.")
    sys.exit(0)

settings.configure(
    DEBUG=False, SECRET_KEY="prueba", ALLOWED_HOSTS=["testserver"], ROOT_URLCONF=__name__,
    INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", "django.contrib.sessions"],
    MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.csrf.CsrfViewMiddleware"],
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
)
django.setup()

from django.test import Client, RequestFactory  # noqa: E402

from asistente_core import Atajo, Toolkit, llm  # noqa: E402
from asistente_core.chat import usuario_de  # noqa: E402
from asistente_core.django_vistas import crear_vistas, urlpatterns_asistente  # noqa: E402

TK = Toolkit(schemas=[], functions={}, system_prompt="x", nombre_app="App", saludo="¡Hola desde Django!",
             atajos=[Atajo("un RFC", r"(?P<dato>[A-Z]{4}\d{6}[A-Z0-9]{3})", lambda r, d: f"Resultado local para {d}.")])
SESION = {"activa": True}
urlpatterns = urlpatterns_asistente(TK, autenticado=lambda request: SESION["activa"])


def _post(cliente, cuerpo, token=None):
    cabeceras = {"HTTP_X_CSRFTOKEN": token} if token else {}
    return cliente.post("/asistente/chat", data=json.dumps(cuerpo), content_type="application/json", **cabeceras)


def test_sin_sesion_responde_401_en_json():
    SESION["activa"] = False
    try:
        r = _post(Client(), {"mensaje": "hola"})
        assert r.status_code == 401 and r.json()["detail"] == "No autenticado"
    finally:
        SESION["activa"] = True


def test_el_script_lleva_el_saludo_y_deja_la_cookie_csrf():
    r = Client().get("/asistente/asistente.js")
    assert r.status_code == 200 and r["Content-Type"].startswith("application/javascript")
    assert "¡Hola desde Django!" in r.content.decode("utf-8") and "X-CSRFToken" in r.content.decode("utf-8")
    assert "csrftoken" in r.cookies, "la vista del script debe dejar la cookie del token"


def test_el_chat_exige_el_token_csrf_y_con_token_funciona():
    cliente = Client(enforce_csrf_checks=True)
    token = cliente.get("/asistente/asistente.js").cookies["csrftoken"].value
    assert _post(cliente, {"mensaje": "hola"}).status_code == 403, "sin token debe rechazarse"
    original = llm.responder
    llm.responder = lambda m, h, request, tk: {"reply": f"eco: {m}", "chart_spec": None, "tabla": None,
                                                "historial": h, "tool_trace": []}
    try:
        r = _post(cliente, {"mensaje": "hola", "historial": []}, token)
    finally:
        llm.responder = original
    assert r.status_code == 200 and r.json()["reply"] == "eco: hola"


def test_un_atajo_se_contesta_sin_el_modelo():
    llamadas = []
    original = llm.responder
    llm.responder = lambda *a, **k: llamadas.append(1) or {"reply": "x", "historial": [], "tool_trace": []}
    try:
        r = _post(Client(), {"mensaje": "dame ABCD800101XYZ", "historial": []})
    finally:
        llm.responder = original
    assert r.json()["reply"] == "Resultado local para ABCD800101XYZ." and not llamadas


def test_peticiones_mal_formadas_dan_400_y_otros_metodos_405():
    c = Client()
    assert _post(c, {"mensaje": "   "}).status_code == 400
    assert _post(c, {"mensaje": "hola", "historial": "no es lista"}).status_code == 400
    assert c.post("/asistente/chat", data="no es json", content_type="application/json").status_code == 400
    assert c.get("/asistente/chat").status_code == 405


def test_el_usuario_para_el_limite_sale_del_usuario_de_django():
    pedido = RequestFactory().get("/")
    pedido.user = SimpleNamespace(is_authenticated=True, get_username=lambda: "ana")
    assert usuario_de(pedido) == "ana"
    anonimo = RequestFactory().get("/", REMOTE_ADDR="8.8.8.8")
    anonimo.user = SimpleNamespace(is_authenticated=False, get_username=lambda: "")
    assert usuario_de(anonimo) == "8.8.8.8"


def test_apagado_no_expone_rutas():
    os.environ.pop("ASISTENTE_ACTIVO")
    try:
        assert urlpatterns_asistente(TK) == []
    finally:
        os.environ["ASISTENTE_ACTIVO"] = "1"


def test_vista_directa_con_usuario_autenticado_por_defecto():
    chat, _ = crear_vistas(TK)
    pedido = RequestFactory().post("/asistente/chat", data=json.dumps({"mensaje": "hola"}), content_type="application/json")
    pedido.user = SimpleNamespace(is_authenticated=False)
    assert chat(pedido).status_code == 401, "por defecto exige request.user.is_authenticated"


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok     {nombre}")
            except Exception:
                import traceback
                fallos += 1
                print(f"FALLA  {nombre}")
                traceback.print_exc()
    print("\nTodo bien." if not fallos else f"\n{fallos} prueba(s) fallaron.")
    sys.exit(1 if fallos else 0)
