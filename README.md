# asistente-core — el asistente de datos para dashboards

Este paquete es el **motor** del chatbot que ya funciona en el dashboard de
adeudos. Cada dashboard lo instala y solo aporta lo suyo: qué datos tiene y qué
preguntas puede responder. Esta guía es para que alguien **sin mucha experiencia
programando** pueda montarlo en otro dashboard. Sigue los pasos en orden.

> ¿Quieres entender por qué se hizo así y cómo se construyó? Lee
> [docs/COMO_SE_CONSTRUYO.md](docs/COMO_SE_CONSTRUYO.md).

---

## 1. Qué es esto, en palabras simples

Es un chat que aparece como un botón flotante en la esquina del dashboard. La
gente le pregunta cosas en español normal ("¿cuántas cuentas hay en la colonia
Centro?") y le pide reportes: cortos, con una gráfica, o largos y explicados, de
varias páginas, con botón de imprimir o guardar como PDF.

Lo que hay que entender antes de tocar nada:

- **No inventa datos.** Solo puede usar una lista cerrada de "herramientas"
  (funciones de Python) que alguien programó a propósito. Si algo no está en esa
  lista, debe decir que no puede, no adivinar.
- **No se conecta a ninguna base de datos en vivo.** Usa los mismos datos que el
  dashboard ya tiene cargados en memoria.
- **Los datos nunca salen del dashboard.** El paquete no sabe nada de columnas ni
  de bases de datos: cada dashboard le entrega sus propias herramientas. Por eso
  un dashboard **no puede** ver los datos de otro.
- **El "cerebro" es intercambiable:** Claude (de pago, por internet, más confiable)
  u Ollama (gratis, corre en la propia computadora, menos confiable). Se elige
  con una variable (ver sección 7).

---

## 2. Cómo está repartido

**Vive en este paquete (igual para todos los dashboards, no se toca):**

```
src/asistente_core/
  toolkit.py       ← ejecuta las herramientas y las protege (tipos, nulls, errores)
  prompts.py       ← las reglas del chatbot (no inventar cifras, no transcribir tablas...)
  llm.py           ← elige Claude u Ollama
  providers/       ← habla con Claude / con Ollama
  informe.py       ← arma la página del reporte largo
  router.py        ← crea el endpoint /asistente/chat
  static/asistente.js  ← el botón de chat (lo sirve el paquete, no se copia)
```

**Lo escribe cada dashboard (3 archivos en su carpeta `app/asistente/`):**

```
app/asistente/
  tools.py     ← LAS FUNCIONES de ese dashboard (lo único que sí hay que programar)
  contexto.py  ← una descripción del dashboard y las secciones de su reporte largo
  router.py    ← junta lo anterior con el paquete (se copia casi tal cual)
```

---

## 3. Antes de empezar

- [ ] El dashboard nuevo ya funciona por su cuenta (FastAPI, con sus datos
      cargados en memoria) y tiene su propio `.venv`.
- [ ] Elegiste el "cerebro": una API key de Anthropic (Claude), o Ollama
      instalado (ver sección 7).
- [ ] Este paquete está en una carpeta **al lado** del dashboard:

```
C:\Trabajo argenrum\
  asistente-core\        ← este paquete
  mi-dashboard\          ← el dashboard donde lo vas a instalar
```

---

## 4. Instalarlo en un dashboard nuevo, paso a paso

### Paso 1 — Instalar el paquete en el dashboard

Desde la carpeta del dashboard:

```powershell
cd "C:\Trabajo argenrum\mi-dashboard"
.venv\Scripts\python.exe -m pip install -e ../asistente-core
```

El `-e` ("editable") hace que el dashboard use directamente la carpeta del
paquete: si el paquete se arregla, **todos los dashboards se benefician sin
reinstalar**.

### Paso 2 — Crear `app/asistente/tools.py` (lo único que hay que programar)

Cada función responde un tipo de pregunta. Recibe `request` primero y regresa un
diccionario. Ejemplo con un dashboard inventado de tickets de soporte:

```python
from app.datasets import datos   # como sea que TU dashboard te dé sus datos


def resumen_tickets(request, solo_abiertos: bool = False) -> dict:
    """Cuenta total de tickets y cuántos están abiertos o cerrados."""
    df = datos(request).tickets
    if solo_abiertos:
        df = df[df["estado"] == "abierto"]
    return {
        "total": int(len(df)),
        "abiertos": int((df["estado"] == "abierto").sum()),
        "cerrados": int((df["estado"] == "cerrado").sum()),
    }


# Una entrada por función. "name" debe ser IDÉNTICO al nombre de la función.
TOOL_SCHEMAS = [
    {
        "name": "resumen_tickets",
        "description": "Cuenta total de tickets y cuántos están abiertos o cerrados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "solo_abiertos": {"type": "boolean", "description": "Si es true, solo cuenta los abiertos."},
            },
        },
    },
]

FUNCIONES = {"resumen_tickets": resumen_tickets}
```

Si el nombre de una herramienta no coincide con su función, el dashboard **avisa
al arrancar** con un mensaje que dice exactamente cuál no cuadra.

**Reglas al escribir cada función:**

1. Nunca regreses nombres, direcciones, teléfonos ni identificaciones oficiales.
2. Si algo no se encuentra, regresa `{"error": "explicación"}` en vez de dejar que truene.
3. Limita cuántas filas regresas (por ejemplo `.head(20)`); nunca mandes una tabla completa.

**Si quieres un reporte largo**, haz una herramienta llamada `reporte_extenso` que
regrese un diccionario con estas llaves (el paquete arma la página con ellas):

| Llave | Qué es |
|---|---|
| `titulo` | Título del reporte |
| `kpis` | Diccionario `{"Etiqueta": valor}` para las tarjetas de arriba |
| `chart_specs` | Diccionario de gráficas Plotly, cada una `{"traces": [...], "layout": {...}}` |
| `hechos_clave` | Lista de frases **ya calculadas y redactadas por ti**; el modelo las cita, no las calcula |
| `tabla_detalle` | (opcional) filas de detalle; **el modelo no la ve**, solo se muestra al usuario |
| `titulo_tabla` | (opcional) título de esa tabla |

**Haz que tus herramientas regresen texto ya redactado.** Además de los números, incluye una
`frase` (o una lista `frases`) con la cifra ya formateada, por ejemplo
`"Hay 11,349 cuentas con adeudo de $10,000 a $20,000."`. El modelo la cita en vez de calcular
o redondear por su cuenta, que es donde se equivocaba ("25 millones y medio" cuando eran 25.0).

**Una herramienta por tipo de pregunta, con ejemplos en su descripción.** Si no existe una
herramienta para una pregunta, el modelo usa la más parecida con una métrica equivocada y
luego inventa el resto. Mejor agregar la herramienta que esperar que el modelo se las arregle.

### Paso 3 — Crear `app/asistente/contexto.py`

```python
DESCRIPCION = "Eres el asistente de datos del dashboard de tickets de soporte."
REGLAS_PROPIAS = []          # reglas del dominio, cada una empieza con "- "
REPORTE_CORTO = ""           # cuándo usar el reporte rápido, si tienes uno
SECCIONES_REPORTE_EXTENSO = ["## Resumen ejecutivo", "## Tickets por estado", "## Limitaciones y alcance"]
NOTA_REPORTE = ""            # una frase para el pie de los reportes
```

### Paso 4 — Crear `app/asistente/router.py`

Cópialo del dashboard de adeudos y cambia solo `nombre_app` y de dónde sale el
nombre del conjunto de datos. Este archivo hace que, **si el paquete no está
instalado, el dashboard arranque igual** (solo sin chat).

Si tu dashboard tiene reporte largo, ese archivo también le pasa al `Toolkit` las
instrucciones de redacción: `instrucciones_reporte=construir_instrucciones_reporte(SECCIONES_REPORTE_EXTENSO)`.
Esas instrucciones **no van en el prompt general**: viajan dentro del resultado de la
herramienta `reporte_extenso`, y por eso el modelo solo las ve cuando va a escribir un reporte.

### Paso 5 — Conectarlo

En el `main.py` del dashboard:

```python
from app.asistente.router import router as asistente_router
# ...junto a los demás routers:
app.include_router(asistente_router)
```

En la plantilla base (el HTML común a todas las páginas), una línea:

```html
<script src="/asistente/asistente.js"></script>
```

### Paso 6 — Configurar el cerebro y levantarlo

PowerShell (ojo: `export` es de Linux y **no** funciona aquí; se usa `$env:`):

```powershell
cd "C:\Trabajo argenrum\mi-dashboard"
$env:ASISTENTE_PROVIDER="ollama"            # o "anthropic"
$env:ASISTENTE_MODEL_OLLAMA="llama3.2"      # si usas ollama
# $env:ANTHROPIC_API_KEY="sk-ant-..."       # si usas anthropic
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Abre `http://localhost:8000`: el botón de chat aparece abajo a la derecha.

### Paso 7 — Medirlo (no te lo saltes)

Con modelos locales chicos, **cambiar una sola frase del prompt puede hacer que
pase de acertar 10 de 10 a 0 de 10** (nos pasó; ver sección 6). Por eso hay un
script que mide el asistente con una batería de preguntas cuyas respuestas
correctas se calculan de tus datos reales:

1. Copia `scripts/evaluar_asistente.py` del dashboard de adeudos al tuyo.
2. Cambia solo la función `construir_bateria` por 3 a 5 preguntas de tu dashboard.
3. Córrelo: `.venv\Scripts\python.exe scripts/evaluar_asistente.py 5`

Repítelo **cada vez** que cambies el prompt, las herramientas o el modelo.

### Probar el paquete por separado

Estas pruebas no necesitan ningún modelo ni conexión:

```powershell
cd "C:\Trabajo argenrum\q2.1_2026_adeudos"
.venv\Scripts\python.exe ../asistente-core/tests/test_smoke.py
```

Debe terminar con `Todo bien.`

---

## 5. Cómo actualizar el paquete

Como se instaló en modo editable, basta con modificar la carpeta `asistente-core`
(o traer cambios con `git pull` dentro de ella). Todos los dashboards que la usan
toman el cambio al reiniciar el servidor. **Después de cualquier cambio, corre las
pruebas del paquete y el script de medición de al menos un dashboard.**

---

## 6. Reglas que NO se deben quitar

Existen porque las rompimos por accidente en pruebas reales y vimos las
consecuencias. No son precaución teórica.

- **Nunca le des al modelo una tabla cruda con datos que no debería repetir tal
  cual** (montos, identificadores). En pruebas reales, el modelo llegó a inventar
  montos o a multiplicarlos por 1000 al copiarlos en una respuesta larga. Por eso
  el `Toolkit` tiene `ocultar_al_modelo`: esconde esa tabla al modelo, aunque la
  tabla real (correcta) sí se le muestre al usuario aparte.
- **Nunca le pidas al modelo que compare varios números por su cuenta** ("¿cuál de
  estos 4 es el más grande?"). Se equivocó. Calcula tú la comparación en Python y
  entrégala ya resuelta como un dato más (`hechos_clave`).
- **Nunca expongas columnas de datos personales** (nombre, dirección, teléfono,
  identificaciones oficiales) en lo que regresa una función.
- **Todo cambio de prompt, de herramientas o de modelo se mide, no se supone.**
  Con `llama3.2` (3B), mover una regla de lugar o cambiar unas palabras bajó una
  pregunta simple de 10/10 aciertos a 0-1 de 10, y revertir *cualquiera* de los tres
  cambios la devolvía a 9-10 de 10: el modelo es frágil ante la redacción exacta. Si
  una redacción ya funciona, no la "mejores" sin correr el script de medición.
- **Las instrucciones del reporte largo no van en el prompt general.** Estando ahí, el modelo
  contagiaba el formato de reporte ("## Sección...") a TODAS las respuestas (32 de 32), y una
  regla de "no uses encabezados" no lo evitaba (0 de 40). Entregarlas dentro del resultado de la
  herramienta lo resolvió (20 de 20).
- **Si el dashboard tiene un filtro global (como `excluir_gc`), todas las herramientas deben aceptarlo.**
  Los modelos lo mandan en todas las llamadas. Una herramienta que no lo declara da error, y el modelo
  lo cuenta como "no puedo" o inventa la respuesta.
- **Una prueba solo vale si cambia una sola cosa.** Aquí se probaron cuatro redacciones distintas
  del prompt para arreglar el RFC y todas dieron 0: tenían en común una llamada que fallaba por un
  parámetro inexistente, que nadie había revisado. Antes de probar redacciones, mira la llamada a la
  herramienta y su resultado crudo.

---

## 7. Eligiendo el "cerebro": Claude vs. modelo local (Ollama)

Esto lo probamos a fondo con datos reales, así que son observaciones basadas
en evidencia, no en teoría.

### 7.1 Instalar Ollama (solo si van a usar la opción gratis/local)

Si van a usar Claude, se saltan toda esta sección — solo necesitan la API key
(ver sección 4, Paso 6).

1. Entrar a **https://ollama.com/download** y descargar el instalador para su
   sistema operativo (Windows, Mac o Linux).
2. Correr el instalador como cualquier programa normal (siguiente, siguiente,
   finalizar). No pide configuración especial.
3. Al terminar, Ollama queda corriendo solo en segundo plano (van a ver un
   ícono en la barra de tareas/menú). No hace falta abrir nada más — arranca
   automáticamente cada vez que prende la computadora.
4. Para confirmar que quedó instalado y corriendo, abran una terminal
   (PowerShell) y escriban:

   ```powershell
   ollama list
   ```

   Si responde con una tabla (aunque esté vacía, sin modelos todavía), Ollama
   está funcionando. Si dice que el comando no se reconoce, hay que cerrar y
   volver a abrir la terminal (a veces no toma el cambio hasta reiniciar la
   ventana), o reiniciar la computadora si sigue sin aparecer.

### 7.2 Descargar un modelo

Ollama no trae modelos instalados por default — hay que descargarlos uno por
uno. Para el modelo que recomendamos empezar a probar:

```powershell
ollama pull llama3.2
```

Esto descarga unos 2GB la primera vez (tarda unos minutos dependiendo del
internet). Ya después queda guardado en la computadora, no se vuelve a
descargar.

Para ver qué modelos ya tienen descargados en cualquier momento:

```powershell
ollama list
```

### 7.3 Verificar que un modelo sirve para esto (soporte de "tools")

No cualquier modelo funciona — el chatbot necesita que el modelo soporte
específicamente "tool calling" (que sepa pedir usar una función). Antes de
usar cualquier modelo, verifiquen con:

```powershell
ollama show nombre-del-modelo
```

y busquen la palabra `tools` dentro de la sección `Capabilities` que imprime.
Si no aparece, ese modelo **no sirve** para este chatbot — no va a poder
llamar ninguna herramienta aunque se lo pidan, y lo más probable es que
alucine una respuesta en su lugar.

### 7.4 Qué modelo elegir — evidencia real, no teoría

Probamos varios modelos con las mismas preguntas exactas contra los mismos
datos reales de este dashboard. Esto fue lo que encontramos (no lo que "se
supone" que debería pasar por tamaño):

| Modelo | ¿Soporta tools? | Qué tan bien nos funcionó |
|---|---|---|
| `llama3.2` (3B, ~2GB) | Sí | **El que mejor funcionó**, sorprendentemente, siendo el más chico de los tres |
| `mistral` (7B, ~4.4GB) | Sí | No llamó la herramienta cuando debía — inventó una respuesta completa en su lugar |
| `qwen2.5:14b` (~9.5GB) | Sí | Saturó una tarjeta gráfica de 12GB de VRAM y puso lenta toda la computadora |
| `gemma3` | **No** | Ollama ni siquiera le pone la etiqueta `tools` — descartado de entrada |

**Conclusión práctica: empiecen con `llama3.2`.** Es el más chico, el más
rápido, y en nuestras pruebas fue el más confiable de los tres. Solo prueben
un modelo más grande si `llama3.2` falla seguido en su caso de uso específico
— y aun así, midan con evidencia (repitan la misma pregunta varias veces),
no asuman que "más grande = mejor" para esta tarea en particular.

**Sobre el tamaño de su tarjeta gráfica (GPU):** si tienen una GPU con poca
memoria de video (menos de 8GB), no intenten modelos de 14B o más — se
comieron 9.5GB en nuestra prueba y dejaron la computadora casi inservible
mientras el modelo estaba cargado. Revisen cuánta VRAM tiene su tarjeta antes
de descargar un modelo grande "por probar".

### 7.5 Claude vs. Ollama — resumen

| | Claude (de pago) | Ollama / modelo local (gratis) |
|---|---|---|
| Confiabilidad | Alta | Variable — a veces perfecto, a veces falla |
| Costo | Por uso (API) | Gratis, pero necesita una computadora con suficiente RAM/GPU |
| Privacidad | Los datos viajan a la API de Anthropic | Nada sale de la computadora |
| Reportes largos | Se puede confiar más | Puede acortar el texto, repetirse, o fallar en seguir instrucciones |
| Instalación | Solo una API key | Instalar Ollama + descargar un modelo (ver arriba) |

### 7.6 Opcional: un segundo modelo solo para redactar los reportes largos

`llama3.2` es bueno para elegir la herramienta correcta y malo para escribir
textos largos: cuando se le piden 700–900 palabras entrega 140–310 y a veces se
salta secciones. Para eso existe el **modelo redactor**: un segundo modelo que
**solo escribe el texto del reporte largo**. Recibe únicamente las instrucciones
y los datos agregados del reporte (nunca la tabla de cuentas ni nombres), y
`llama3.2` sigue haciendo todo lo demás (elegir herramientas, responder
preguntas cortas).

Activarlo es una sola variable (vacía = desactivado):

```powershell
ollama pull gemma3:12b
$env:ASISTENTE_MODEL_REDACTOR_OLLAMA="gemma3:12b"
```

Qué esperar (medido con los datos reales, 6 reportes por configuración):

| | Solo `llama3.2` | Con redactor `gemma3:12b` |
|---|---|---|
| Palabras por reporte (se piden 700–900) | 140–310 | 735–873 (promedio 805) |
| Secciones pedidas presentes | a veces faltan | 6 de 6 reportes completos |
| Cifras que no estaban en los datos | — | ninguna |
| Tiempo por reporte | segundos | ~21–28 s |

Cosas que hay que saber:

- **Memoria de la tarjeta gráfica (VRAM):** `gemma3:12b` ocupa unos 8 GB. En una
  GPU de 12 GB caben los dos modelos pero ajustado; Ollama cambia de uno a otro
  y por eso el primer reporte tarda más. El redactor se descarga solo de la
  memoria 1 minuto después de usarse (`keep_alive`) para no frenar la computadora.
  Con menos de 8 GB libres **no lo activen**.
- **Si el redactor falla** (Ollama apagado, modelo no descargado) el reporte lo
  escribe el modelo principal, igual que sin redactor, y la consola muestra una
  `ADVERTENCIA`. Nadie se queda sin reporte.
- **`gemma3` no sirve como modelo principal** (no soporta tools, ver 7.4), pero para
  redactar no hace falta que las soporte.
- **Cada dashboard debe dar contexto al redactor.** El redactor no conoce el
  dominio; el `Toolkit` tiene un campo `contexto_redactor` (2–3 frases: qué es el
  dashboard y qué miden sus números). Sin él, `gemma3` interpretó los scores de
  riesgo de impago como "riesgo crediticio". Con el contexto: 0 veces de 6.
- **No agreguen reglas al redactor sin medir.** Se probó añadir "no especules sobre
  causas": quitaba la especulación pero **acortaba los reportes de 804 a 510
  palabras**. El contexto del dominio corrige el encuadre sin acortar.
  Siguen apareciendo, rara vez, frases suaves de especulación (2 en 6 reportes);
  se revisan con la batería (`python scripts/evaluar_asistente.py`).
- **Cuidado al medir:** corran la batería de a una configuración a la vez. Tres
  corridas pesadas seguidas con `gemma3:12b` hicieron que la computadora se
  cayera; el script de pruebas que usamos es reanudable y espera si la GPU pasa de 80 °C.

---

## 8. Problemas comunes (ya nos pasaron, ya los resolvimos)

**`export` no se reconoce como comando**
Estás en PowerShell, no en bash. Usa `$env:VARIABLE="valor"`.

**`.venv\Scripts\python.exe` no se encuentra**
Estás en la carpeta equivocada. Entra con `cd` a la carpeta del dashboard.

**`ModuleNotFoundError` o "no se encontró el paquete asistente-core"**
El paquete no está instalado en el `.venv` de ese dashboard. Corre
`.venv\Scripts\python.exe -m pip install -e ../asistente-core` desde la carpeta
del dashboard. (Sin el paquete el dashboard arranca igual, solo sin chat.)

**Al arrancar: "El Toolkit no cuadra"**
Una herramienta de `TOOL_SCHEMAS` no tiene su función en `FUNCIONES` (o al
revés). El mensaje dice cuál; el `name` debe ser idéntico al nombre de la llave.

**Error `Falta configurar ANTHROPIC_API_KEY`**
Pon la llave con `$env:ANTHROPIC_API_KEY="..."`, o cambia `ASISTENTE_PROVIDER` a
`ollama` para usar el modelo local.

**El chat responde con números raros o inventados**
Sospecha primero del modelo, sobre todo con Ollama. Pregunta lo mismo varias
veces: si a veces sale bien y a veces mal, es el modelo, no tu `tools.py`. Mide
con el script (Paso 7). Considera un modelo más grande o Claude para ese caso.

**Cambié una frase del prompt y el chat se puso a inventar**
Es el comportamiento descrito en la sección 6. Deshaz el cambio y vuelve a medir.

**La computadora se pone muy lenta al usar el chat**
El modelo local usa más memoria de video de la que tiene la tarjeta. Cierra el
modelo (`ollama stop nombre-modelo`) y prueba uno más chico.

**El botón de chat no aparece**
Revisa que la plantilla base tenga `<script src="/asistente/asistente.js">` y que
el router esté registrado en `main.py`. Abre `http://localhost:8000/asistente/asistente.js`:
debe mostrar código, no un error.

**Todas las respuestas salen como reporte ("## Sección...")**
Pasa si las instrucciones del reporte largo están en el prompt general. Deben ir solo en
`instrucciones_reporte` del `Toolkit` (ver Paso 4). Agregar una regla de "no uses encabezados"
al prompt NO lo arregla.

**El asistente dice "no puedo" (o "por privacidad") aunque la herramienta sí tiene el dato**
Casi siempre es que la herramienta falló por un parámetro que no existe: los modelos le agregan
`excluir_gc` (u otro) a todas las llamadas y, si la herramienta no lo declara, da error; el modelo
después explica ese error como "no puedo por restricciones de privacidad". Pasó con la pregunta
del RFC (0 de 6 hasta corregirlo). Revisa la herramienta con una llamada directa, sin el modelo, y
declara el parámetro. El error del `Toolkit` ahora lista los parámetros válidos y le pide al modelo
reintentar, pero declarar el parámetro es lo más seguro.

**Pido un reporte "de la colonia X" y sale el de todo el padrón**
Limitación conocida de `llama3.2`: a veces no pasa el nombre a la herramienta (en
nuestras pruebas, 0 de 6 veces). Hacer el parámetro obligatorio no ayudó. Con un
modelo más grande o con Claude conviene volver a probar.

---

## 9. Antes de dar por terminada la instalación

- [ ] Paquete instalado en el `.venv` del dashboard (`pip install -e ../asistente-core`)
- [ ] `tools.py`, `contexto.py` y `router.py` creados en `app/asistente/`
- [ ] Router registrado en `main.py` y `<script>` en la plantilla base
- [ ] El proveedor está configurado (Claude u Ollama) y el servidor levanta sin errores
- [ ] El botón de chat aparece y responde con datos reales
- [ ] Probaste una pregunta que el chatbot NO puede responder, y dijo que no puede
- [ ] Si hay reportes largos: el texto no inventa cifras de detalle
- [ ] Corriste el script de medición (Paso 7) y anotaste los resultados
