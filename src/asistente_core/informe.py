"""
Arma el HTML de un "reporte extenso": una página standalone (con Plotly
embebido vía CDN) que combina la narrativa redactada por el modelo con los
datos y gráficas que ya vinieron de la herramienta `reporte_extenso` del
dashboard — nunca al revés.
Así lo que se ve en tablas y gráficas siempre es exacto (viene de Python),
aunque la prosa que las explica la haya escrito el LLM.

No requiere ninguna dependencia nueva (sin weasyprint/kaleido): el botón
"Imprimir / Guardar como PDF" usa el diálogo de impresión del navegador.
"""
from __future__ import annotations

import datetime
import html
import json
import re

_ENCABEZADO = re.compile(r"^(#{2,3})\s+(.*)$")
_NEGRITA = re.compile(r"\*\*(.+?)\*\*")
# Modelos más chicos (sobre todo locales vía Ollama) no siempre siguen el
# formato "## Sección" que se les pide en el prompt: en la práctica usan una
# línea entera en negritas como título ("**Resumen ejecutivo**"). Se trata
# igual que un encabezado real SOLO cuando ocupa la línea completa — una
# negrita dentro de una oración normal no debe convertirse en título.
_LINEA_NEGRITA_COMO_TITULO = re.compile(r"^\*\*(.+?)\*\*:?$")
_MARCAS_TITULO = re.compile(r"^#+\s*|\*\*")


def _quitar_titulo_duplicado(narrativa: str, titulo: str) -> str:
    """Si la primera línea no vacía del texto repite el título del reporte
    (a veces pasa aunque el prompt pida no hacerlo), se descarta esa línea —
    ya se muestra como <h1> arriba, repetirlo como <h2> se ve mal."""
    lineas = (narrativa or "").splitlines()
    for i, linea in enumerate(lineas):
        limpia = linea.strip()
        if not limpia:
            continue
        texto_plano = _MARCAS_TITULO.sub("", limpia).strip().rstrip("*").strip()
        if texto_plano.lower() == titulo.strip().lower():
            return "\n".join(lineas[:i] + lineas[i + 1:])
        break
    return narrativa


def _texto_a_html(texto: str) -> str:
    """Conversión mínima de markdown a HTML: encabezados ##/###, listas con -, negritas **x**."""
    html_partes: list[str] = []
    parrafo: list[str] = []
    en_lista = False

    def cerrar_parrafo():
        if parrafo:
            html_partes.append("<p>" + " ".join(parrafo) + "</p>")
            parrafo.clear()

    def cerrar_lista():
        nonlocal en_lista
        if en_lista:
            html_partes.append("</ul>")
            en_lista = False

    for linea in (texto or "").splitlines():
        linea = linea.strip()
        m = _ENCABEZADO.match(linea)
        if m:
            cerrar_parrafo()
            cerrar_lista()
            nivel = len(m.group(1))
            html_partes.append(f"<h{nivel}>{html.escape(m.group(2))}</h{nivel}>")
            continue
        m = _LINEA_NEGRITA_COMO_TITULO.match(linea)
        if m:
            cerrar_parrafo()
            cerrar_lista()
            html_partes.append(f"<h2>{html.escape(m.group(1))}</h2>")
            continue
        if linea.startswith(("- ", "* ")):
            cerrar_parrafo()
            if not en_lista:
                html_partes.append("<ul>")
                en_lista = True
            html_partes.append(f"<li>{html.escape(linea[2:])}</li>")
            continue
        if not linea:
            cerrar_parrafo()
            cerrar_lista()
            continue
        parrafo.append(html.escape(linea))

    cerrar_parrafo()
    cerrar_lista()
    salida = "\n".join(html_partes)
    return _NEGRITA.sub(r"<strong>\1</strong>", salida)


_PLANTILLA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{titulo}</title>
<meta name="color-scheme" content="light">
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  /* Documento pensado para imprimirse/exportarse a PDF: fondo blanco fijo,
     sin importar el tema (claro/oscuro) del navegador del usuario. */
  html {{ background: #fff; }}
  body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 800px; margin: 2.5rem auto; padding: 0 1.5rem; color: #1e293b; line-height: 1.65; background: #fff; }}
  h1 {{ font-size: 1.6rem; border-bottom: 3px solid #0f172a; padding-bottom: .5rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 2rem; color: #0f172a; }}
  h3 {{ font-size: 1.05rem; color: #334155; }}
  .meta {{ color: #64748b; font-size: .85rem; margin-bottom: 2rem; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .75rem; margin: 1.5rem 0; }}
  .kpi {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; text-align: center; }}
  .kpi .valor {{ font-size: 1.3rem; font-weight: 700; color: #0f172a; font-family: Georgia, serif; }}
  .kpi .etiqueta {{ font-size: .7rem; color: #64748b; text-transform: uppercase; letter-spacing: .02em; }}
  .chart {{ height: 320px; margin: 1.5rem 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .8rem; margin: 1rem 0; }}
  th, td {{ border: 1px solid #e2e8f0; padding: .4rem .6rem; text-align: left; }}
  th {{ background: #f1f5f9; }}
  .nota {{ font-size: .78rem; color: #64748b; border-top: 1px solid #e2e8f0; margin-top: 2rem; padding-top: 1rem; }}
  @media print {{ body {{ margin: 0; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>
<button class="no-print" onclick="window.print()"
  style="float:right;padding:.5rem 1rem;background:#0d6efd;color:#fff;border:0;border-radius:6px;cursor:pointer;font-family:sans-serif">
  Imprimir / Guardar como PDF
</button>
<h1>{titulo}</h1>
<div class="meta">{meta}</div>

<div class="kpis">{kpis_html}</div>

{narrativa_html}

{charts_html}

{tabla_html}

<div class="nota">{nota_html}</div>
</body>
</html>"""


def construir_reporte_html(
    *, titulo: str, dataset: str, narrativa: str,
    kpis: dict, chart_specs: dict, tabla: list[dict] | None,
    titulo_tabla: str = "Detalle", nombre_app: str = "", nota: str = "",
) -> str:
    fecha = datetime.date.today().isoformat()
    narrativa = _quitar_titulo_duplicado(narrativa, titulo)

    partes_meta = [f"Generado el {fecha}"]
    if dataset:
        partes_meta.append(f"Dataset: {html.escape(dataset)}")
    partes_meta.append(
        f"Asistente de datos — {html.escape(nombre_app)}" if nombre_app else "Asistente de datos"
    )
    meta = " &middot; ".join(partes_meta)

    nota_html = " ".join(p for p in (
        "Este reporte fue generado automáticamente a partir de los datos cargados en el dashboard.",
        html.escape(nota) if nota else "",
        "El texto explicativo fue redactado por un modelo de lenguaje a partir de las cifras "
        "mostradas arriba; en caso de discrepancia, las cifras de las tablas y gráficas son la fuente correcta.",
    ) if p)

    kpis_html = "".join(
        f'<div class="kpi"><div class="valor">{html.escape(str(v))}</div>'
        f'<div class="etiqueta">{html.escape(k)}</div></div>'
        for k, v in (kpis or {}).items()
    )

    def _json_para_script(obj) -> str:
        # Escapa SOLO "</" dentro del JSON (por si algún texto trae "</script>"
        # literal) sin tocar las etiquetas <script>/</script> reales del
        # template — hacerlo sobre el snippet completo rompía el cierre del
        # tag y arrastraba todo lo siguiente (2da gráfica, tabla, </html>)
        # como texto sin renderizar.
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    charts_html = ""
    for i, (_nombre, spec) in enumerate((chart_specs or {}).items()):
        div_id = f"chart-{i}"
        charts_html += f'<div id="{div_id}" class="chart"></div>\n'
        charts_html += (
            f'<script>Plotly.newPlot("{div_id}", '
            f'{_json_para_script(spec.get("traces", []))}, '
            f'{_json_para_script(spec.get("layout", {}))});</script>\n'
        )

    tabla_html = ""
    if tabla:
        cols = list(tabla[0].keys())
        filas = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(f.get(c, '')))}</td>" for c in cols) + "</tr>"
            for f in tabla
        )
        tabla_html = (
            f"<h2>{html.escape(titulo_tabla)}</h2><table><thead><tr>"
            + "".join(f"<th>{html.escape(c)}</th>" for c in cols)
            + f"</tr></thead><tbody>{filas}</tbody></table>"
        )

    return _PLANTILLA.format(
        titulo=html.escape(titulo),
        meta=meta,
        nota_html=nota_html,
        kpis_html=kpis_html,
        narrativa_html=_texto_a_html(narrativa),
        charts_html=charts_html,
        tabla_html=tabla_html,
    )
