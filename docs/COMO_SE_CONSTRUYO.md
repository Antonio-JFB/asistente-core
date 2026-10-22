# Cómo se construyó `asistente-core`

Documento para explicar, con detalle, qué se hizo, por qué, cómo se comprobó que
funciona y qué falta. Todas las cifras de este documento salen de pruebas que se
corrieron de verdad con los datos del dashboard de adeudos; donde algo no se
pudo comprobar, se dice.

## 1. En cinco líneas

1. El chatbot del dashboard de adeudos funcionaba, pero estaba **mezclado con el
   dashboard**: para usarlo en otro había que copiar archivos a mano, y cada
   arreglo había que repetirlo en cada copia.
2. Se separó en dos partes: un **paquete reutilizable** (`asistente-core`, el motor)
   y lo **propio de cada dashboard** (sus herramientas de consulta y su contexto).
3. Los datos **nunca salen de cada dashboard**: el paquete no tiene acceso a
   ninguna base de datos, solo ejecuta las herramientas que el dashboard le da.
4. Se comprobó con pruebas automáticas y con una batería de preguntas reales
   contra el modelo local. Al hacerlo se encontró una **regresión real** (explicada
   en la sección 5) que se corrigió antes de dar el trabajo por bueno.
5. Pendiente: probar con Claude (no había llave disponible), probar con un segundo
   dashboard, y subir el paquete a GitHub.

## 2. Punto de partida

El asistente vivía dentro de `q2.1_2026_adeudos/app/asistente/` con siete piezas:
las herramientas de consulta (`tools.py`), la conexión con Claude y con Ollama
(`providers/`), el armado del reporte largo (`informe.py`), el prompt
(`prompts.py`), el selector de proveedor (`llm.py`), el endpoint (`router.py`) y
el botón de chat (`asistente.js`).

De esas piezas, solo `tools.py` conoce los datos de adeudos. Las demás son
iguales para cualquier dashboard, pero estaban pegadas a él: por ejemplo, los
proveedores importaban directamente el `tools.py` del dashboard.

## 3. La decisión: qué arquitectura usar

Se pensó centralizar el chatbot en un servicio aparte al que cada dashboard le
haga peticiones. Se evaluaron tres caminos:

| Opción | Cómo funciona | Veredicto |
|---|---|---|
| **A. Paquete compartido** | El motor vive en un repo; cada dashboard lo instala y aporta solo sus herramientas | **Elegida** |
| B. Servicio central que solo corre la IA | El servicio habla con el modelo y, cuando este pide una herramienta, le llama de regreso al dashboard | Posible más adelante; añade autenticación entre servicios y dos despliegues |
| C. Servicio central con acceso directo a todas las bases de datos | Un solo servicio lee los datos de todos | **Descartada** |

**Por qué se descartó la C:** el aislamiento entre dashboards dependería de que un
filtro nunca falle. Un error o una pregunta mal intencionada podría mezclar datos
de un dashboard con otro, y se concentraría en un solo lugar el acceso a datos
sensibles (RFC, adeudos). **Regla adoptada: centralizar el código, no los datos.**
Con la opción A cada dashboard solo puede tocar sus propios datos *por
construcción* (nunca los tiene a la mano el paquete), no por un filtro.

**Por qué A y no B:** quienes lo van a montar en otros dashboards no son muy
técnicos; "instalar un paquete y escribir un archivo" es mucho más sencillo que
"desplegar y conectar dos servicios".

## 4. Cómo se construyó, paso a paso

1. **Red de seguridad.** Se creó una rama nueva (`feature/asistente-core`) a partir
   de la versión que ya funcionaba (`feature/asistente-ia`). Esa versión quedó
   intacta como respaldo.
2. **Se separó lo genérico de lo específico** y se movió lo genérico a una carpeta
   hermana, `asistente-core`.
3. **Se creó el `Toolkit`**, el contrato entre el motor y un dashboard. El
   dashboard le entrega tres cosas: la lista de herramientas, las funciones que
   las ejecutan y el prompt. El `Toolkit` concentra lo que no debe variar:
   - al arrancar, **verifica que cada herramienta declarada tenga su función** (y al
     revés), con un mensaje que dice cuál no cuadra;
   - **corrige los tipos** que mandan algunos modelos (por ejemplo `"false"` como
     texto, que en Python cuenta como verdadero y activaba un filtro por error);
   - **trata un `null` como "no lo mandé"** y deja que aplique el valor por defecto;
   - **oculta al modelo las tablas de detalle** de un reporte (ver sección 5).
4. **Se rehicieron los proveedores** (Claude y Ollama) para que reciban el
   `Toolkit` en vez de importar el `tools.py` del dashboard. La lógica interna no
   cambió.
5. **Se dividió el prompt:** las reglas generales (no inventar cifras, no
   transcribir tablas, no repetir el título) viven en el paquete; la descripción
   del dashboard y las secciones de su reporte largo viven en el dashboard.
6. **El router pasó a ser una "fábrica"** (`crear_router`) que cada dashboard usa con
   su propio `Toolkit`. El botón de chat ahora lo sirve el propio paquete, así que
   ya no se copia a cada dashboard.
7. **Se adelgazó el dashboard de adeudos:** conserva solo sus funciones
   (`tools.py`), su contexto (`contexto.py`) y un archivo corto que junta todo
   (`router.py`). Si el paquete no está instalado, el dashboard arranca igual,
   solo sin chat.

Para los cambios sobre archivos que ya funcionaban se usaron parches que **abortan
si el texto a reemplazar no coincide exactamente una vez**, en lugar de reescribir
a mano: así un error de transcripción no pasa en silencio.

## 5. Cómo se comprobó, y qué se encontró

### 5.1 Pruebas automáticas del paquete

9 pruebas que no necesitan ningún modelo, y que cubren cosas que de verdad
fallaron antes: nombres que no cuadran entre herramienta y función, tipos
mal enviados, `null`, la tabla oculta al modelo, el HTML del reporte bien
cerrado (un error pasado se "comía" la segunda gráfica y la tabla), el título no
duplicado y el endpoint completo. Resultado: **9 de 9 pasan**.

### 5.2 Batería de preguntas con el modelo local (`llama3.2`)

Se midió con un script (`scripts/evaluar_asistente.py` en el dashboard de adeudos)
que repite cada pregunta varias veces y calcula la respuesta correcta **a partir de
los datos reales**, no escrita a mano.

**Hallazgo principal: una regresión real.** La primera versión del prompt dentro
del paquete, que decía lo mismo con palabras más generales, **hizo fallar una
pregunta simple**: "Dame un resumen general del padrón".

| Prompt | Corridas correctas |
|---|---|
| Anterior (el ya probado) | 10/10 y 10/10 en dos corridas de 10 (y 3/3 en una prueba previa) |
| Nuevo (generalizado) | 0/10, 1/10 y 1/10 en tres corridas de 10 (y 1/3 en una prueba previa) |

Se descartó que fuera un efecto del orden de las pruebas y se buscó la causa
revirtiendo los cambios de redacción uno por uno: **revertir cualquiera de los
tres cambios devolvía el resultado a 9–10 de 10**. La conclusión es que el modelo
chico es **frágil ante la redacción exacta**; no existe "la frase culpable".

**Solución:** el dashboard de adeudos conserva exactamente la redacción y el orden
de reglas que ya estaban probados (el paquete lo permite con dos parámetros) y se
agregó una regla permanente al README: *todo cambio de prompt o de modelo se mide,
no se supone.*

**Resultado final**, misma batería, 6 corridas por pregunta, prompt anterior contra
la configuración final:

| Pregunta | Prompt anterior | Configuración final |
|---|---|---|
| Resumen general del padrón | 6/6 | 6/6 |
| Buscar la cuenta por NIS | 6/6 | 6/6 |
| Top colonias por adeudo | 6/6 | 6/6 |
| Cuántas cuentas críticas | 3/6 | 6/6 |
| Reporte extenso de la colonia Centro | 0/6 | 0/6 |

### 5.3 Otros problemas encontrados y corregidos al probar

- **Parámetros `null`.** En 2 de 8 búsquedas por NIS el modelo mandó `limit: null` y
  la función tronó con `int(None)`. Se corrigió en el `Toolkit` (beneficia a todos
  los dashboards) y tiene su prueba.
- **Etiquetas en el identificador.** El modelo manda `NIS=123`, `NIS/Padrón:123`, etc.
  Se generalizó la limpieza: se verificó con 13 variantes, incluyendo nombres que
  **no** deben alterarse (`Nissan Pérez`, `Idalia Ramos`).
- **Se bloqueaba el dashboard.** El endpoint de chat era `async` pero llama al modelo
  de forma bloqueante, lo que detendría todo el dashboard mientras el modelo
  responde (de segundos a minutos). Ahora es una función normal, que FastAPI corre
  en otro hilo. *Esta mejora se hizo por razonamiento y no se midió.*

### 5.4 Prueba en navegador

Con el servidor real: el botón de chat aparece, el script se carga desde el paquete
(`/asistente/asistente.js`) y una pregunta llega, usa la herramienta correcta y
responde con el total real del padrón (333,081 cuentas).

### 5.5 Segunda ronda: respuestas mal hechas que reportó un usuario

Un usuario pasó cuatro respuestas malas reales del conjunto de datos de Municipio. Antes de
arreglar nada se reprodujeron (3 corridas cada una) para ver qué herramienta llamaba el modelo y se
calculó la respuesta correcta a partir de los datos. Resultado: **solo una de las cuatro era un
problema de redacción; las otras tres eran huecos o errores de las herramientas.**

| Pregunta del usuario | Qué pasaba | Causa real |
|---|---|---|
| 5 colonias con mayor adeudo | Herramienta correcta, pero respuesta con formato de reporte y comentarios inventados ("el gobierno municipal no paga") | Formato de reporte contagiado por el prompt |
| Colonia con más contribuyentes de riesgo medio | Usó la métrica equivocada y luego inventó una tabla | **No existía herramienta** para contar cuentas por prioridad |
| Cuántos adeudos entre 10,000 y 20,000 | Respondió "419,579" (todo el padrón) | **No existía herramienta** de rangos, y una búsqueda vacía devolvía todo el padrón |
| Adeudo de un RFC | Respondió "$0.00" | La herramienta solo devolvía 10 de las 9,017 cuentas de ese RFC; faltaba una que sume. Ya con la herramienta nueva, fallaba por un parámetro que no declaraba (ver abajo) |

**Línea base (antes de arreglar, 4 corridas por pregunta):** 32 de 32 respuestas simples salieron con
encabezados de reporte; las tres preguntas de Municipio sin herramienta acertaron 0 de 4.

**Qué se cambió:**
1. Las instrucciones del reporte largo dejaron de estar en el prompt general y ahora viajan dentro
   del resultado de la herramienta del reporte. Antes de elegir esta solución se probaron dos
   alternativas: una regla explícita de "no uses encabezados" en dos posiciones del prompt
   (**0 de 40** respuestas lo respetaron) y esta (**20 de 20**).
2. Tres herramientas nuevas: contar cuentas por rango de adeudo, colonias con más cuentas en una
   prioridad, y adeudo total de un contribuyente por RFC (no devuelve nombre). Sus resultados se
   verificaron contra los datos antes de probar con el modelo (11,349 cuentas; PUERTA REAL con 1,140;
   9,017 cuentas con $307,935,418 para ese RFC).
3. Una búsqueda vacía ahora da un error en vez de devolver todo el padrón.
4. Cuando una herramienta falla, su resultado incluye la instrucción de no inventar nada.
5. Las herramientas devuelven frases ya redactadas con las cifras formateadas, para que el modelo
   no redondee a su manera.
6. Se amplió el script de medición: ahora cubre Municipio, revisa el formato y verifica que **nunca
   se filtren el nombre ni el domicilio reales**.
7. Las herramientas de búsqueda y de RFC aceptan `excluir_gc` (el modelo lo manda en todas las
   llamadas), y cuando un modelo manda un parámetro que no existe, el error ahora lista los
   válidos y le pide reintentar.

**Resultado final (6 corridas por pregunta, `llama3.2`):**

| Pregunta | Antes | Después |
|---|---|---|
| AguaH: resumen general | 0/4 (formato) | **6/6** |
| AguaH: buscar cuenta por NIS | 0/4 (formato) | **6/6** |
| AguaH: top colonias por adeudo | 0/4 (formato) | **6/6** |
| AguaH: cuántas cuentas críticas | 0/4 (formato) | **6/6** |
| Municipio: top 5 colonias | 0/4 | **6/6** |
| Municipio: colonia con más cuentas de riesgo medio | 0/4 | **6/6** |
| Municipio: adeudos entre 10,000 y 20,000 | 0/4 | **6/6** |
| Municipio: no revelar nombre ni domicilio | (no medida) | **6/6** |
| Municipio: adeudo de un RFC | 0/4 | **6/6** |
| AguaH: reporte extenso de la colonia Centro | 0/4 | 0/6 (limitación conocida) |

**Lo que se probó y no funcionó** (se revirtió o se descartó):
- Una regla de "no uses encabezados" en el prompt: 0 de 40.
- Hacer obligatorio el nombre de la colonia: 0 de 8.
- Reescribir la regla de privacidad para que no mencione el RFC: no arregló la pregunta del RFC y
  **rompió otra** ("cuántas cuentas críticas" pasó de 4/4 a 1/4). Se restauró la redacción original.
- **Un diagnóstico equivocado del RFC.** Se probaron cuatro variantes (regla original, sin la regla,
  con una nota de autorización, sin la palabra RFC en el resultado) y todas dieron 0 de 5; se
  concluyó que el modelo se negaba por su propio entrenamiento y se construyó un mecanismo de
  "respuesta directa" para saltárselo. Era un error: las cuatro variantes compartían una llamada
  que fallaba porque el modelo mandaba `excluir_gc` a una herramienta que no lo declaraba, y el
  modelo explicaba ese error como "no puedo por privacidad". Se verificó llamando a la herramienta
  sin el modelo. Al corregir el parámetro el RFC contesta 6 de 6 **con y sin** ese mecanismo, que se
  retiró por innecesario. Lección: antes de probar redacciones, revisar el resultado crudo de la
  herramienta.

**Decisión de privacidad (ya tomada):** la herramienta de RFC devuelve montos para cualquier RFC que
escriba una persona autenticada, lo mismo que ya le da el buscador del "Ranking de cuentas". No
devuelve nombre ni domicilio, y eso lo vigila una pregunta de la batería. La persona que entregó los
datos confirmó que el asistente debe dar esas cifras.

### 5.6 Tercera ronda: un modelo redactor para los reportes largos

**Problema:** con `llama3.2` los reportes largos salían cortos (140 a 310 palabras cuando se piden
700 a 900) y a veces sin todas las secciones. Un modelo local más grande (`qwen2.5:14b`) ya se
había descartado por saturar la tarjeta gráfica.

**Idea:** no cambiar el modelo que elige herramientas (que funciona), sino agregar un segundo
modelo que **solo escribe la narrativa del reporte**. Recibe las instrucciones y los datos
agregados (nunca la tabla de cuentas) y devuelve el texto. `gemma3:12b` no sabe usar herramientas,
pero para redactar no las necesita. Si falla, se usa el texto del modelo principal.

**Cómo se midió** (misma métrica automática, 6 reportes por configuración: 3 del padrón completo y
3 de la colonia Centro; cifras fuera de los datos, secciones, palabras y frases especulativas):

| Configuración del redactor | Palabras (prom.) | Secciones completas | Frases especulativas | Cifras inventadas |
|---|---|---|---|---|
| Sin instrucciones extra | 804 | 6/6 | 7 (causas inventadas, "riesgo crediticio" en afirmativo) | 0 |
| Regla "no especules" + contexto del dominio | 604 | 6/6 | 0 | 0 |
| Solo la regla "no especules" | 510 | 6/6 | 0 | 0 |
| **Solo el contexto del dominio (elegida)** | **805** | **6/6** | 2 leves | 0 |

Hallazgos:
- Con `gemma3:12b` la longitud y las secciones se resuelven (735 a 873 palabras) sin cifras inventadas.
- Sin ayuda, el redactor interpretó los scores como "riesgo crediticio" y supuso causas. Esos
  scores miden riesgo de **no pagar el adeudo**, no solvencia.
- La regla "no especules" corrige eso pero **recorta el texto un 37 %**. Lo que corrige sin recortar
  es explicar qué es el dashboard y qué miden sus números (`contexto_redactor`). Se eligió eso.
- Al principio concluí al revés (que el contexto era lo que acortaba): era la regla. Se separaron las
  dos variables y se midió cada una sola. Misma lección que en 5.5: **cambiar una cosa a la vez**.
- La métrica contaba como errores frases negadas ("no representa un riesgo crediticio", "no incluye
  especulaciones sobre las causas"), que son justo lo deseable. Se corrigió para que no cuenten.

**Prueba de punta a punta** (`llama3.2` elige la herramienta, `gemma3:12b` redacta, pregunta "reporte
completo del padrón", 3 corridas): 723, 750 y 787 palabras, las 5 secciones en las 3, una sola frase
especulativa ("causas subyacentes") y una cifra marcada (`50.2%` donde el valor es 50.27 %: truncado
en vez de redondeado, no inventado; la batería ahora tolera ese truncamiento). En una corrida
anterior Ollama cortó la conexión con `gemma3` (error 500) y el sistema usó el respaldo
(`llama3.2`): salió un reporte corto, que es el comportamiento previsto pero muestra que el redactor
puede fallar. La batería completa (Municipio incluido) **no se terminó con el redactor activo**;
sin redactor sí está medida (sección 5.5).

**Incidente:** tras tres corridas pesadas seguidas con `gemma3:12b` la computadora se cayó. Se
verificó que ningún archivo del proyecto quedara dañado (compila, 18 pruebas pasan) y se repitió con
precauciones: una configuración a la vez, resultados guardados al instante (reanudable), espera si la
GPU pasa de 80 °C y descarga del modelo al terminar.

**Costos de usarlo:** unos 8 GB de VRAM, 21 a 28 segundos por reporte y un cambio de modelo en la
tarjeta gráfica (el primer reporte tarda más). Se descarga de la memoria 1 minuto después de usarse.

### 5.7 Cuarta ronda: primera prueba real con Claude y preparación para producción

Hasta aquí todo se había medido con modelos locales. Con una llave de la API (se pidió una nueva porque
la primera no pertenecía a un *workspace* y la API la rechazaba) se corrió la batería de 11 preguntas:

| Configuración | Resultado | Costo por corrida |
|---|---|---|
| Claude solo | 10 de 11 preguntas 3/3; el reporte largo del padrón 0/3 por corto (497 a 536 palabras) | ≈ 1.3 a 1.6 ¢ por pregunta corta; ≈ 3 ¢ por reporte |
| Claude + redactor Claude | **11 de 11, 3/3** | ≈ 5 ¢ por reporte largo |

- El redactor con Claude (llamada aparte, sin herramientas, mismas instrucciones y contexto) da 961, 981 y
  977 palabras, sin frases especulativas ni cifras fuera de los datos.
- "Reporte de la colonia Centro", la limitación que `llama3.2` nunca superó (0 de 6), con Claude es 3 de 3.
- Una pregunta de seguimiento sobre el historial funciona (se probó). El historial que viaja al navegador no
  lleva los bloques de razonamiento del modelo, porque el redactor puede reescribir la respuesta.

Cambios hechos para llevarlo a producción sin riesgo:
- **Interruptor `ASISTENTE_ACTIVO`** (apagado por defecto): sin él no hay botón ni rutas.
- **Topes** por persona y por día, y de gasto diario; **registro de tokens y costo** por consulta.
- **Esfuerzo de razonamiento** fijado en `medium` (más barato) y `ASISTENTE_MODEL` vacío ya no rompe el modelo.
- **Falla amable:** sin saldo o sin red el usuario no ve un error técnico.
- Pruebas del paquete: de 18 a 24.

Lo que aún no está medido: un periodo largo de uso real (el costo por pregunta es una estimación con una
sola persona consultando) y el comportamiento con muchos usuarios a la vez.

## 6. Limitaciones que siguen abiertas

1. **El reporte "de la colonia X" sale del padrón completo con `llama3.2`.** El modelo
   no pasa el nombre de la colonia a la herramienta: 0 de 6 veces, también con el
   prompt anterior (no es una regresión de este trabajo). Se probó hacer el
   parámetro obligatorio: **no ayudó** (0 de 8) y se revirtió. **Con Claude sí funciona** (3 de 3, sección 5.7).
2. **Claude se probó solo en el dashboard de adeudos**, con una persona consultando (sección 5.7). Falta
   medir el costo con uso real y en los demás dashboards.
3. **Los modelos locales chicos son frágiles** (sección 5.2). Es una propiedad del
   modelo, no del paquete; por eso se agregó el script de medición.
4. **Solo se probó en un dashboard.** La promesa "solo hay que escribir `tools.py`"
   se comprueba de verdad con un segundo dashboard.
5. **Los reportes largos salen cortos con `llama3.2` solo** (140 a 310 palabras, cuando se piden 700
   a 900). Se resuelve con el modelo redactor opcional (sección 5.6), que necesita unos 8 GB de VRAM.
   Con redactor siguen apareciendo, rara vez, frases suaves de especulación (2 en 6 reportes).
6. **El buscador de texto de `app/utils.py` trata lo escrito como expresión regular** (avisa
   con una advertencia si el texto trae paréntesis). Afecta también al buscador del dashboard;
   no se cambió por ser código compartido con la interfaz.

## 7. Qué cambia para el equipo

| | Antes | Ahora |
|---|---|---|
| Instalar en otro dashboard | Copiar 7 archivos y editar varios | Instalar el paquete y escribir 3 archivos cortos |
| Un arreglo en el motor | Repetirlo en cada copia | Una vez, y todos lo reciben |
| Los datos de cada dashboard | En su propio proceso | Igual: nunca pasan por el paquete |
| Comprobar que no se rompió algo | A ojo | Pruebas automáticas + script de medición |

## 8. Estado y siguientes pasos

- **El trabajo está sin subir ni confirmar (commit):** el paquete es una carpeta
  nueva fuera de git y los cambios del dashboard están en la rama local
  `feature/asistente-core`.
- `main` ya avanzó (se integró `feature/descriptivos-adeudos`) y esta rama sale de
  una versión anterior: al integrarla habrá que hacer un *merge* y revisar posibles
  conflictos.

Siguientes pasos sugeridos: (1) correr la batería con Claude; (2) crear el repo
de `asistente-core` en GitHub y marcar una versión `v0.1.0`; (3) montarlo en un
segundo dashboard como piloto; (4) hacer el *merge* a `main`.
