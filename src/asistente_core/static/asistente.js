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

  let historial = leerJSON(KEY_HISTORIAL, []);
  let mensajes = leerJSON(KEY_MENSAJES, []);
  let plotlyListo = !!window.Plotly;

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
    btn.innerHTML = '<i class="bi bi-chat-dots-fill"></i>';
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
      '    style="background:transparent;border:0;color:#94a3b8;cursor:pointer;font-size:.8rem"><i class="bi bi-trash"></i></button>' +
      "</div>" +
      '<div id="asistente-msgs" style="flex:1;overflow-y:auto;padding:.6rem;font-size:.85rem;background:#f8fafc"></div>' +
      '<form id="asistente-form" style="display:flex;border-top:1px solid #e2e8f0">' +
      '  <input id="asistente-input" placeholder="Pregunta algo..." autocomplete="off" ' +
      '    style="flex:1;border:0;padding:.6rem;font-size:.85rem;outline:none">' +
      '  <button type="submit" style="border:0;background:#0d6efd;color:#fff;padding:0 .9rem"><i class="bi bi-send-fill"></i></button>' +
      "</form>";

    document.body.appendChild(btn);
    document.body.appendChild(panel);

    btn.onclick = () => {
      panel.style.display = panel.style.display === "none" ? "flex" : "none";
    };

    document.getElementById("asistente-form").addEventListener("submit", enviar);
    document.getElementById("asistente-limpiar").addEventListener("click", vaciar);

    // Restaura la conversación de páginas anteriores, si había una.
    mensajes.forEach((m) => pintarMensaje(m.rol, m.texto, m.chartSpec, m.tabla, m.reporteHtml));
  }

  function vaciar() {
    historial = [];
    mensajes = [];
    guardar();
    document.getElementById("asistente-msgs").innerHTML = "";
  }

  async function enviar(e) {
    e.preventDefault();
    const input = document.getElementById("asistente-input");
    const texto = input.value.trim();
    if (!texto) return;
    input.value = "";
    agregarMensaje("user", texto);

    try {
      const resp = await fetch("/asistente/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mensaje: texto, historial }),
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      historial = data.historial || historial;
      agregarMensaje("assistant", data.reply || "(sin respuesta)", data.chart_spec, data.tabla, data.reporte_html);
    } catch (err) {
      agregarMensaje("assistant", "Ocurrió un error al consultar el asistente.");
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

  function abrirReporte(htmlReporte) {
    const blob = new Blob([htmlReporte], { type: "text/html" });
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
      boton.onclick = () => abrirReporte(reporteHtml);
      cont.appendChild(boton);
    }

    cont.scrollTop = cont.scrollHeight;
  }

  document.addEventListener("DOMContentLoaded", crearPanel);
})();
