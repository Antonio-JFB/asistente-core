"""
Arma el system prompt. Las reglas que protegen contra errores ya vistos en
pruebas reales (inventar cifras, transcribir tablas, repetir el título) viven
aquí y son iguales para todos los dashboards; cada dashboard solo aporta su
descripción, sus propias reglas y las secciones de su reporte extenso.
"""
from __future__ import annotations

from typing import Sequence

REGLAS_GENERALES = (
    "- Solo puedes responder usando las herramientas disponibles. Nunca inventes cifras.",
    "- Si la pregunta no se puede resolver con las herramientas disponibles, dilo con claridad.",
)

REGLA_DATOS_PERSONALES = (
    "- Nunca reveles datos personales de ninguna persona (nombre, domicilio, identificaciones "
    "oficiales): las herramientas ya los excluyen a propósito."
)

# Va siempre al final de la lista. Con llama3.2 (3B) se midió que el orden de las
# reglas y su redacción cambian el resultado de forma drástica (ver docs).
REGLA_IDIOMA = "- Responde siempre en español."

# Solo remite al reporte largo; las instrucciones completas llegan con el resultado de la herramienta.
_PUNTERO_REPORTE_EXTENSO = (
    "Para reportes largos ('completo', 'extenso', 'detallado') usa `reporte_extenso` y sigue las "
    "instrucciones de redacción que trae su resultado. Usa encabezados '##' ÚNICAMENTE en un reporte "
    "extenso. En cualquier otra respuesta escribe 2-4 frases en prosa simple, sin encabezados, sin "
    "secciones y sin tablas."
)


def construir_instrucciones_reporte(secciones: Sequence[str]) -> str:
    """Instrucciones para redactar el reporte largo. NO van en el system prompt: el Toolkit
    las entrega dentro del resultado de `reporte_extenso`. Estando siempre en el prompt,
    llama3.2 contagiaba el formato de reporte a TODAS las respuestas (32 de 32 salían con
    encabezados) y una regla de "no uses encabezados" no lo evitaba (0 de 40)."""
    lista = "\n".join(secciones)
    primera = secciones[0].split(" (")[0]
    return f"""Reportes extensos (herramienta `reporte_extenso`): úsalos cuando pidan un reporte
"completo", "extenso", "detallado", "elaborado" o de varias cuartillas/páginas.
En ese caso redacta un informe largo (mínimo 700-900 palabras) organizado con
encabezados markdown ("## Sección"), en este orden:

{lista}

No empieces tu respuesta repitiendo el título del reporte como encabezado — ya
se muestra arriba en la página, empieza directo con "{primera}".

Para el contenido de cada sección usa EXCLUSIVAMENTE las cifras que trae
`hechos_clave` y los demás campos de la herramienta — no calcules porcentajes
nuevos, no redondees distinto, no inventes ningún número que no esté ahí. Antes
de afirmar cuál categoría es "la más común" o "la mayoría", revisa el hecho
que ya la identifica en vez de asumirlo por tu cuenta.

Si el reporte trae una tabla de detalle (`tabla_detalle`), NO transcribas montos,
identificadores ni cifras de filas individuales del JSON crudo — transcribir
números de una tabla suele salir mal. Esos datos exactos ya se muestran en una
tabla aparte debajo del reporte. En la sección que hable de esas filas escribe
solo 1-2 frases generales (si eso está en `hechos_clave`) y remite
explícitamente a la tabla de abajo para el detalle.

Puedes explicar qué significa cada cifra, dar contexto y señalar qué NO se
puede concluir de ella, pero no agregues datos que la herramienta no te dio.
""".strip()


def construir_system_prompt(
    descripcion: str,
    reglas_propias: Sequence[str] = (),
    reporte_corto: str = "",
    secciones_reporte_extenso: Sequence[str] | None = None,
    regla_datos_personales: str | None = None,
) -> str:
    """
    descripcion: una frase que presenta al asistente y su dashboard.
    reglas_propias: reglas específicas del dominio (cada una empieza con "- ").
    reporte_corto: texto opcional que explica cuándo usar el reporte rápido.
    secciones_reporte_extenso: encabezados ("## Resumen ejecutivo", ...) en el
        orden en que debe redactarse el reporte largo. Si es None, el prompt no
        menciona el reporte extenso. Las secciones en sí no van en el prompt: se entregan con
        `construir_instrucciones_reporte` dentro del resultado de esa herramienta (ver Toolkit).
    regla_datos_personales: redacción propia de la regla de privacidad (con "- "
        al inicio). Si es None se usa REGLA_DATOS_PERSONALES.

    Orden de las reglas: generales, datos personales, las propias del dashboard e
    idioma al final.
    """
    reglas = "\n".join([
        *REGLAS_GENERALES,
        regla_datos_personales or REGLA_DATOS_PERSONALES,
        *reglas_propias,
        REGLA_IDIOMA,
    ])
    partes = [descripcion.strip(), "Reglas generales:\n" + reglas]
    if reporte_corto.strip():
        partes.append(reporte_corto.strip())
    if secciones_reporte_extenso:
        partes.append(_PUNTERO_REPORTE_EXTENSO)
    return "\n\n".join(partes) + "\n"
