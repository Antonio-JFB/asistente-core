/**
 * Widget de chat del asistente. Llama a POST /asistente/chat y renderiza
 * texto, tabla y (si la herramienta usada regresa chart_spec) una gráfica de
 * Plotly, cargado bajo demanda para no pesar en páginas donde no se abre.
 *
 * La conversación persiste en localStorage (mismo patrón que ya usa
 * seleccion.js para el carrito): el sidebar navega con recarga completa de
 * página, así que sin esto el chat se reiniciaría cada vez que el usuario
 * cambia de sección. Se limpia sola al cambiar de dataset (ver setDataset()
 * en base.html) porque las cifras de una conversación no aplican al otro
 * padrón.
 */
(function () {
  const KEY_HISTORIAL = "asistente_historial";
  const KEY_MENSAJES = "asistente_mensajes";

  function leerJSON(key, porDefecto) {
    try {
      const val = JSON.parse(localStorage.getItem(key));
      return val ?? porDefecto;
    } catch (e) {
      return porDefecto;
    }
  }

  // El servidor antepone window.ASISTENTE_CONFIG = {saludo: "..."} (ver router.py). Sin él, saludo genérico.
  const CFG = window.ASISTENTE_CONFIG || {};

  // Íconos en línea (SVG): así el botón se ve igual aunque el dashboard no cargue Bootstrap Icons.
  const svg = (d) => '<svg xmlns="http://www.w3.org/2000/svg" width="1.2em" height="1.2em" viewBox="0 0 24 24" fill="currentColor" ' +
    'style="vertical-align:-.2em" aria-hidden="true"><path d="' + d + '"/></svg>';
  const ICONO_CHAT = svg("M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z");
  const ICONO_BORRAR = svg("M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z");
  const ICONO_ENVIAR = svg("M2.01 21L23 12 2.01 3 2 10l15 2-15 2z");
  const SALUDO = CFG.saludo ||
    "¡Hola! Soy el asistente de datos de este dashboard. Pregúntame por cifras o rankings, o pídeme un reporte completo que puedas descargar en PDF.";

  let historial = leerJSON(KEY_HISTORIAL, []);
  let mensajes = leerJSON(KEY_MENSAJES, []);
  let plotlyListo = !!window.Plotly;
  let esperando = false;

  // Animación de los tres puntitos mientras el asistente prepara la respuesta.
  function inyectarEstilos() {
    if (document.getElementById("asistente-estilos")) return;
    const st = document.createElement("style");
    st.id = "asistente-estilos";
    st.textContent =
      "@keyframes asistente-salto{0%,60%,100%{transform:translateY(0);opacity:.35}30%{transform:translateY(-4px);opacity:1}}" +
      ".asistente-punto{display:inline-block;width:7px;height:7px;margin:0 2px;border-radius:50%;background:#64748b;" +
      "animation:asistente-salto 1.2s infinite ease-in-out}" +
      ".asistente-punto:nth-child(2){animation-delay:.15s}.asistente-punto:nth-child(3){animation-delay:.3s}" +
      "@media (prefers-reduced-motion:reduce){.asistente-punto{animation:none;opacity:.7}}";
    document.head.appendChild(st);
  }

  function burbujaAsistente(htmlInterno, id) {
    const cont = document.getElementById("asistente-msgs");
    const fila = document.createElement("div");
    if (id) fila.id = id;
    fila.style.marginBottom = ".6rem";
    fila.style.textAlign = "left";
    const span = document.createElement("span");
    Object.assign(span.style, {
      display: "inline-block", padding: ".4rem .7rem", borderRadius: "10px",
      background: "#e2e8f0", color: "#0f172a", maxWidth: "90%",
    });
    span.innerHTML = htmlInterno;
    fila.appendChild(span);
    cont.appendChild(fila);
    cont.scrollTop = cont.scrollHeight;
    return fila;
  }

  // Saludo al abrir el chat cuando todavía no hay conversación. No se guarda ni se manda al modelo.
  function mostrarSaludo() {
    if (mensajes.length || document.getElementById("asistente-saludo")) return;
    const fila = burbujaAsistente("", "asistente-saludo");
    fila.firstChild.textContent = SALUDO;
  }

  function mostrarEscribiendo() {
    quitarEscribiendo();
    const fila = burbujaAsistente(
      '<span class="asistente-punto"></span><span class="asistente-punto"></span><span class="asistente-punto"></span>',
      "asistente-escribiendo");
    fila.firstChild.setAttribute("aria-label", "El asistente está escribiendo");
    // Los reportes largos tardan hasta un minuto: se avisa para que nadie piense que se trabó.
    fila._aviso = setTimeout(() => {
      const nota = document.createElement("div");
      nota.style.cssText = "font-size:.72rem;color:#64748b;margin-top:.25rem";
      nota.textContent = "Esto puede tardar un poco si es un reporte...";
      fila.firstChild.appendChild(nota);
      document.getElementById("asistente-msgs").scrollTop = 1e9;
    }, 8000);
  }

  function quitarEscribiendo() {
    const fila = document.getElementById("asistente-escribiendo");
    if (!fila) return;
    clearTimeout(fila._aviso);
    fila.remove();
  }

  function bloquearEntrada(bloquear) {
    esperando = bloquear;
    const input = document.getElementById("asistente-input");
    const enviarBtn = document.querySelector("#asistente-form button[type=submit]");
    input.disabled = bloquear;
    enviarBtn.disabled = bloquear;
    enviarBtn.style.opacity = bloquear ? ".5" : "1";
    if (!bloquear) input.focus();
  }

  function guardar() {
    try {
      localStorage.setItem(KEY_HISTORIAL, JSON.stringify(historial));
      localStorage.setItem(KEY_MENSAJES, JSON.stringify(mensajes));
    } catch (e) {
      // localStorage lleno o bloqueado: la conversación sigue funcionando,
      // solo no persiste entre páginas.
    }
  }

  function cargarPlotly(cb) {
    if (plotlyListo) return cb();
    const s = document.createElement("script");
    s.src = "https://cdn.plot.ly/plotly-2.27.0.min.js";
    s.onload = () => { plotlyListo = true; cb(); };
    document.head.appendChild(s);
  }

  function crearPanel() {
    const btn = document.createElement("button");
    btn.id = "asistente-btn";
    btn.title = "Asistente de datos";
    btn.innerHTML = ICONO_CHAT;
    Object.assign(btn.style, {
      position: "fixed", bottom: "20px", right: "20px", zIndex: 1050,
      width: "52px", height: "52px", borderRadius: "50%", border: "0",
      background: "#0d6efd", color: "#fff", fontSize: "1.3rem",
      boxShadow: "0 2px 10px rgba(0,0,0,.3)", cursor: "pointer",
    });

    const panel = document.createElement("div");
    panel.id = "asistente-panel";
    Object.assign(panel.style, {
      position: "fixed", bottom: "84px", right: "20px", width: "360px", maxWidth: "92vw",
      height: "480px", background: "#fff", borderRadius: "10px",
      boxShadow: "0 4px 24px rgba(0,0,0,.25)", display: "none", flexDirection: "column",
      overflow: "hidden", zIndex: 1050,
    });
    panel.innerHTML =
      '<div style="background:#0f172a;color:#fff;padding:.6rem .9rem;font-weight:600;font-size:.9rem;display:flex;justify-content:space-between;align-items:center">' +
      '  <span>Asistente de datos</span>' +
      '  <button id="asistente-limpiar" title="Vaciar conversación" ' +
      '    style="background:transparent;border:0;color:#94a3b8;cursor:pointer;font-size:.8rem">' + ICONO_BORRAR + '</button>' +
      "</div>" +
      '<div id="asistente-msgs" style="flex:1;overflow-y:auto;padding:.6rem;font-size:.85rem;background:#f8fafc"></div>' +
      '<form id="asistente-form" style="display:flex;border-top:1px solid #e2e8f0">' +
      '  <input id="asistente-input" placeholder="Pregunta algo..." autocomplete="off" ' +
      '    style="flex:1;border:0;padding:.6rem;font-size:.85rem;outline:none">' +
      '  <button type="submit" style="border:0;background:#0d6efd;color:#fff;padding:0 .9rem">' + ICONO_ENVIAR + '</button>' +
      "</form>";

    document.body.appendChild(btn);
    document.body.appendChild(panel);

    btn.onclick = () => {
      const abrir = panel.style.display === "none";
      panel.style.display = abrir ? "flex" : "none";
      if (abrir) {
        mostrarSaludo();
        const input = document.getElementById("asistente-input");
        if (!input.disabled) input.focus();
      }
    };

    document.getElementById("asistente-form").addEventListener("submit", enviar);
    document.getElementById("asistente-limpiar").addEventListener("click", vaciar);
    document.getElementById("asistente-msgs").setAttribute("aria-live", "polite");
    inyectarEstilos();

    // Restaura la conversación de páginas anteriores, si había una.
    mensajes.forEach((m) => pintarMensaje(m.rol, m.texto, m.chartSpec, m.tabla, m.reporteHtml));
  }

  function vaciar() {
    historial = [];
    mensajes = [];
    guardar();
    document.getElementById("asistente-msgs").innerHTML = "";
    if (esperando) mostrarEscribiendo();   // la respuesta que viene en camino se pintará después
    else mostrarSaludo();
  }

  // Django exige el token CSRF en las peticiones POST: se lee de la cookie `csrftoken` si existe (FastAPI no la usa).
  function cabeceras() {
    const h = { "Content-Type": "application/json" };
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) h["X-CSRFToken"] = decodeURIComponent(m[1]);
    return h;
  }

  async function enviar(e) {
    e.preventDefault();
    if (esperando) return;
    const input = document.getElementById("asistente-input");
    const texto = input.value.trim();
    if (!texto) return;
    input.value = "";
    agregarMensaje("user", texto);
    bloquearEntrada(true);
    mostrarEscribiendo();

    try {
      const resp = await fetch("/asistente/chat", {
        method: "POST",
        headers: cabeceras(),
        credentials: "same-origin",
        body: JSON.stringify({ mensaje: texto, historial }),
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      historial = data.historial || historial;
      quitarEscribiendo();
      agregarMensaje("assistant", data.reply || "(sin respuesta)", data.chart_spec, data.tabla, data.reporte_html);
    } catch (err) {
      quitarEscribiendo();
      agregarMensaje("assistant", "Ocurrió un error al consultar el asistente.");
    } finally {
      bloquearEntrada(false);
    }
  }

  // Guarda el mensaje (para que sobreviva a la próxima navegación) y lo pinta.
  // reporteHtml es la página completa de un "reporte extenso" (2+ cuartillas);
  // se guarda tal cual para poder reabrirla aunque el usuario navegue de página.
  function agregarMensaje(rol, texto, chartSpec, tabla, reporteHtml) {
    mensajes.push({ rol, texto, chartSpec, tabla, reporteHtml });
    guardar();
    pintarMensaje(rol, texto, chartSpec, tabla, reporteHtml);
  }

  // paraPdf: abre el reporte y lanza el diálogo de impresión del navegador (ahí se elige "Guardar como PDF").
  // Se espera a que carguen las gráficas antes de imprimir.
  function abrirReporte(htmlReporte, paraPdf) {
    const html = paraPdf
      ? htmlReporte.replace("</body>",
          "<script>window.addEventListener('load',function(){setTimeout(function(){window.print()},2500)})<\/script></body>")
      : htmlReporte;
    const blob = new Blob([html], { type: "text/html" });
    window.open(URL.createObjectURL(blob), "_blank");
  }

  function pintarMensaje(rol, texto, chartSpec, tabla, reporteHtml) {
    const cont = document.getElementById("asistente-msgs");

    const burbuja = document.createElement("div");
    burbuja.style.marginBottom = ".6rem";
    burbuja.style.textAlign = rol === "user" ? "right" : "left";
    const span = document.createElement("span");
    Object.assign(span.style, {
      display: "inline-block", padding: ".4rem .7rem", borderRadius: "10px",
      background: rol === "user" ? "#0d6efd" : "#e2e8f0",
      color: rol === "user" ? "#fff" : "#0f172a", maxWidth: "90%",
    });
    span.textContent = texto;
    burbuja.appendChild(span);
    cont.appendChild(burbuja);

    if (tabla && tabla.length) {
      const cols = Object.keys(tabla[0]);
      const tbl = document.createElement("table");
      tbl.className = "table table-sm";
      tbl.style.fontSize = ".75rem";
      tbl.innerHTML =
        "<thead><tr>" + cols.map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>" +
        tabla.map((f) => "<tr>" + cols.map((c) => `<td>${f[c]}</td>`).join("") + "</tr>").join("") +
        "</tbody>";
      cont.appendChild(tbl);
    }

    if (chartSpec) {
      const div = document.createElement("div");
      div.style.height = "220px";
      div.id = "chart-" + Date.now();
      cont.appendChild(div);
      cargarPlotly(() => Plotly.newPlot(div.id, chartSpec.traces, chartSpec.layout || {}));
    }

    if (reporteHtml) {
      const boton = document.createElement("button");
      boton.textContent = "📄 Abrir reporte completo";
      Object.assign(boton.style, {
        display: "block", margin: ".4rem 0", padding: ".4rem .7rem",
        background: "#0f172a", color: "#fff", border: "0", borderRadius: "6px",
        fontSize: ".78rem", cursor: "pointer",
      });
      boton.onclick = () => abrirReporte(reporteHtml, false);
      cont.appendChild(boton);

      const botonPdf = document.createElement("button");
      botonPdf.textContent = "⬇ Descargar PDF";
      Object.assign(botonPdf.style, {
        display: "block", margin: ".4rem 0", padding: ".4rem .7rem",
        background: "#1d4ed8", color: "#fff", border: "0", borderRadius: "6px",
        fontSize: ".78rem", cursor: "pointer",
      });
      botonPdf.onclick = () => abrirReporte(reporteHtml, true);
      cont.appendChild(botonPdf);
    }

    cont.scrollTop = cont.scrollHeight;
  }

  document.addEventListener("DOMContentLoaded", crearPanel);
})();
