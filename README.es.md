📖 [English](README.md) · **Español**

# FullQA.ai

**Un grabador de sesiones de QA totalmente local que convierte lo que haces en pantalla en documentación de QA profesional y automatización ejecutable — impulsado por IA, organizado por proyecto.**

Graba una sesión de QA (clics, pulsaciones de teclas, capturas de pantalla, narración de voz opcional) y FullQA.ai produce Markdown limpio y listo para copiar y pegar: un resumen, pasos para reproducir, notas de testing exploratorio, casos de prueba, un plan de pruebas, reportes de bug, tickets de Jira — además de un **script de Playwright profesional que puedes ejecutar y ver en un navegador real**. Todo se agrupa por **proyecto**, y cada proyecto puede llevar un **documento de contexto** que hace que la IA sea mucho más precisa sobre *tu* aplicación.

> **Todo se queda en tu máquina.** Los únicos datos que salen son la sesión que envías explícitamente al proveedor de IA que elijas — y con Ollama no sale nada en absoluto. Cero sincronización en la nube, cero telemetría.

---

## Tabla de contenidos

- [Novedades](#novedades)
- [Cómo funciona](#cómo-funciona)
- [Características](#características)
- [Requisitos previos](#requisitos-previos)
- [Inicio rápido](#inicio-rápido)
- [La aplicación de escritorio](#la-aplicación-de-escritorio)
  - [Mis sesiones](#mis-sesiones)
  - [Mis scripts](#mis-scripts)
  - [Grabar](#grabar)
- [Contexto del proyecto — enseñarle a la IA sobre tu producto](#contexto-del-proyecto--enseñarle-a-la-ia-sobre-tu-producto)
- [Testing exploratorio](#testing-exploratorio)
- [Secciones del reporte](#secciones-del-reporte)
- [Scripts de automatización profesionales](#scripts-de-automatización-profesionales)
- [Proveedores de IA](#proveedores-de-ia)
- [Arquitectura](#arquitectura)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Formatos de datos](#formatos-de-datos)
- [Referencia de la API](#referencia-de-la-api)
- [Seguridad](#seguridad)
- [Solución de problemas](#solución-de-problemas)
- [Licencia](#licencia)

---

## Novedades

Las últimas versiones añadieron bastante. Si usaste una versión temprana, esta es la lista corta:

- **Organización por proyectos** — las sesiones y los scripts se agrupan por **proyecto**. Nombra y renombra sesiones; elige un proyecto existente o crea uno nuevo sobre la marcha.
- **Mis sesiones / Mis scripts / Grabar** — una barra lateral de tres secciones. Mis sesiones muestra **miniaturas** para que reconozcas una grabación de un vistazo.
- **Contexto del proyecto** — un documento editable por proyecto que se pasa a la IA en **cada** generación, para que los resultados encajen de verdad con cómo funciona tu producto.
- **Secciones de reporte estructuradas** — elige exactamente lo que quieres: Resumen, Pasos para reproducir, Testing exploratorio, Casos de prueba, Plan de pruebas, Reporte de bug, Ticket Jira.
- **Scripts de Playwright profesionales** — TypeScript limpio y con buenas prácticas (`test.describe` / `test.step`, locators por rol/etiqueta, aserciones web-first) que puedes **Ejecutar** desde la app y ver en un navegador real.
- **Modelos actualizados** — usa por defecto modelos Claude actuales (por ejemplo Claude Sonnet 5), con manejo de *adaptive thinking* y reducción automática del tamaño de las imágenes para respetar los límites del proveedor.

---

## Cómo funciona

```
┌────────────┐   graba      ┌──────────────────────┐   lee/escribe    ┌──────────────────┐
│  Agente     │ ───────────▶ │  qa-sessions/            │ ◀──────────────  │  Backend FastAPI │
│(bandeja,host)│  clics,      │  <fecha>/<uuid>/         │  (volumen        │  (Docker)        │
└────────────┘  teclas,      │   ├ events.jsonl         │   compartido)    │  claude_gen.py   │
     ▲          capturas,     │   ├ screenshots/*.png    │                  │  playwright_gen  │
     │          audio         │   ├ manifest.json        │                  │  + SQLite        │
     │                        │   └ transcript.txt       │                  └────────┬─────────┘
     │                        └──────────────────────┘                           │ IA
┌────┴────────────────────────────────────────────────────────────────────┐    ▼
│  App de escritorio (PyQt6) — Mis sesiones · Mis scripts · Grabar          │  Anthropic / Ollama /
│  explora, nombra, añade contexto, genera docs, ejecuta automatizaciones   │  Groq / Gemini
└──────────────────────────────────────────────────────────────────────────┘
        escribe los specs de Playwright ▶  qa-scripts/<proyecto>/*.spec.ts
```

Cooperan tres procesos:

1. **Agente** (`agent/main.py`) — se ejecuta de forma nativa en el host desde un icono de bandeja. Captura eventos, capturas de pantalla y (opcionalmente) audio narrado en `qa-sessions/`.
2. **Backend** (`services/api`, en Docker) — agrupa los eventos en bruto en pasos con sentido, llama al proveedor de IA y devuelve Markdown. También guarda los metadatos de la sesión (nombre, proyecto) y el contexto por proyecto en SQLite.
3. **App de escritorio** (`desktop/ui.py`) — el centro de control: explorar/organizar sesiones, editar el contexto del proyecto, generar documentación y generar + **ejecutar** scripts de automatización.

---

## Características

**Captura**
- Clics, scroll y pulsaciones de teclas mediante `pynput`; capturas de pantalla con `mss`.
- Captura de scroll inteligente — una captura limpia cuando la rueda *se detiene*, no una por cada tick.
- Narración de voz opcional (ES/EN) transcrita **offline** con `faster-whisper`.
- Objetivo de captura: monitor activo, pantalla completa, un monitor concreto o una sola ventana.
- "Captura inteligente" en vivo opcional: un modelo de visión local guarda una captura solo cuando hay cambios relevantes en pantalla.
- Soporte de extensión de navegador: las sesiones web capturan selectores CSS reales, roles ARIA y nombres accesibles para obtener scripts de alta calidad.

**Organizar**
- **Proyectos**: agrupan sesiones y scripts; renombra sesiones; asigna/crea proyectos desde un desplegable.
- **Miniaturas** en la lista de sesiones para reconocerlas al instante.
- Documento de **contexto del proyecto** por proyecto, inyectado en cada generación de IA.

**Generar**
- Elige secciones: **Resumen / Explicación**, **Pasos para reproducir**, **Testing exploratorio**, **Casos de prueba**, **Plan de pruebas**, **Reporte de bug**, **Ticket Jira**.
- **Recorrido visual** añadido a cada reporte — una captura por paso.
- **Exportación a PDF** (con las capturas incrustadas).
- IA multiproveedor: **Anthropic Claude**, **Ollama** (totalmente local), **Groq**, **Google Gemini**.
- "Probar conexión" lista los modelos realmente instalados/disponibles para Ollama y Gemini.

**Automatizar**
- Un clic convierte una sesión en un **spec de Playwright profesional** y lo archiva en `qa-scripts/<proyecto>/`.
- **Ejecutar** un script desde **Mis scripts** — abre un navegador real (visible y ralentizado) para que veas todo el flujo.

**Robusto**
- Resistente sin conexión: si el backend está caído, la app sigue listando/abriendo sesiones directamente del disco.
- Los metadatos se replican en `manifest.json` en disco, así sobreviven a un reinicio de la base de datos.
- Backend solo en localhost, contenedor sin root, validación contra *path traversal*.

---

## Requisitos previos

| Herramienta | Necesaria para | Notas |
|------|--------------|-------|
| **Python 3.10+** | agente + app de escritorio | [python.org](https://www.python.org) o vía `uv` |
| **Docker Desktop 4.x+** | backend | [docker.com](https://www.docker.com/products/docker-desktop/) — incluye Compose v2 |
| **Un proveedor de IA** | generación | Uno de: clave de Anthropic, clave de Groq, clave de Gemini u Ollama en local |
| **Node.js 18+** | *ejecutar* scripts de automatización | Solo si usas **Mis scripts → Ejecutar** ([nodejs.org](https://nodejs.org)) |

> **Nota para Windows:** si `python` no está en el PATH, usa `uv` para gestionar el venv (ver paso 2), o llama directamente a `.\.venv\Scripts\python.exe`.

---

## Inicio rápido

### 1 — Elige un proveedor de IA (al menos uno)

| Proveedor | Coste | Dónde conseguir la clave |
|----------|------|--------------------|
| **Anthropic Claude** | De pago, mejor calidad | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| **Groq** | Capa gratuita, nube rápida | [console.groq.com](https://console.groq.com) → API Keys |
| **Google Gemini** | Capa gratuita | [aistudio.google.com](https://aistudio.google.com) → Get API key |
| **Ollama** | Gratis, totalmente local | [IA local con Ollama](#ia-local-con-ollama) |

### 2 — Crea el entorno virtual

```powershell
cd C:\ruta\a\FullQA.ai

# Recomendado (uv):
uv venv .venv --python 3.12
uv pip install -r requirements.txt

# O con Python estándar:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3 — Configura las variables de entorno

Copia `.env.example` a `.env` y rellena solo la(s) clave(s) que vayas a usar:

```
ANTHROPIC_API_KEY=sk-ant-tu_clave_aqui
GROQ_API_KEY=gsk_tu_clave_aqui
GEMINI_API_KEY=tu_clave_aqui
OLLAMA_BASE_URL=            # vacío = por defecto http://host.docker.internal:11434/v1
```

> ⚠️ **El archivo `.env` contiene secretos reales — nunca lo subas al repositorio.** Mantén `.env.example` solo con valores vacíos o de ejemplo. Después de editar `.env`, **recrea el contenedor del backend** (abajo) para que tome los valores nuevos — un contenedor en marcha no vuelve a leer `.env`.

### 4 — Arranca el backend en Docker

```powershell
docker compose up -d --build
```

La API arranca en `http://localhost:8000/docs`. La primera vez hace falta `--build`; después basta con `docker compose up -d`. **Cada vez que cambies `.env`, ejecuta `docker compose up -d --force-recreate`.**

### 5 — Abre la app de escritorio

```powershell
.\.venv\Scripts\python.exe desktop\ui.py
```

La píldora **API Online** de la cabecera se pone verde cuando el backend está listo.

### 6 — Arranca el agente de captura

En una segunda terminal:

```powershell
.\.venv\Scripts\python.exe agent\main.py
```

Aparece un icono en la bandeja. Clic derecho → **▶ Iniciar Grabación**.

### 7 — Grabar → organizar → generar → automatizar

1. En **Grabar**, opcionalmente pon un **Nombre sesión** y elige/escribe un **Proyecto**, y empieza a grabar (o hazlo desde la bandeja).
2. Haz tu flujo de QA; detén la grabación al terminar.
3. En **Mis sesiones**, selecciona la grabación (miniatura + nombre), opcionalmente pulsa **Renombrar** y añade **Contexto del proyecto**.
4. En la pestaña **Resumen**, elige secciones + proveedor/modelo y pulsa **Generar Documentación**.
5. Lee el reporte (pestaña **Reporte**); exporta a PDF o copia el Markdown.
6. Marca **Script Playwright** al generar para archivar un spec en **Mis scripts**, y luego pulsa **Ejecutar** para verlo en un navegador.

---

## La aplicación de escritorio

La barra lateral izquierda tiene cuatro secciones.

### Mis sesiones

- Sesiones agrupadas por **proyecto** (las que no tienen proyecto caen en *Sin proyecto*).
- Una **miniatura** (primera captura) por sesión para reconocerla rápido.
- **Renombrar** (botón o doble clic): edita el **nombre** y el **proyecto** de la sesión. El campo de proyecto es un desplegable con los proyectos existentes — escribe un nombre nuevo para crear uno.
- Botón **Contexto del proyecto** (arriba a la derecha del panel de detalle): abre el editor del proyecto de la sesión seleccionada.
- Al seleccionar una sesión se abre el panel de detalle: **Resumen** (generar), **Eventos**, **Reporte**.

### Proyectos

Una vista dedicada para ver y gestionar todos los proyectos. Cada proyecto es una tarjeta que muestra su **número de sesiones**, su **número de scripts** y si tiene documento de **contexto**. Desde aquí puedes:

- **Contexto** — editar el contexto por proyecto que la IA usa en cada generación.
- **Ver sesiones** — saltar a Mis sesiones filtrado por ese proyecto.
- **Scripts** — abrir la carpeta `qa-scripts/` del proyecto.
- **Renombrar** — renombra el proyecto en todos lados (reasigna sus sesiones, mueve su contexto, renombra su carpeta de scripts).
- **Eliminar** — desasigna el proyecto de sus sesiones (las sesiones **no** se borran), limpia su contexto y elimina la carpeta de scripts vacía.
- **＋ Nuevo proyecto** — crea un proyecto y abre su editor de contexto directamente.

### Mis scripts

- Todos los specs de Playwright generados, agrupados por carpeta de proyecto dentro de `qa-scripts/`.
- **▶ Ejecutar** — lanza `npx playwright test --headed` para el spec seleccionado; se abre un navegador real y ralentizado para que veas cada paso. La salida se muestra en un panel de log.
- **Instalar Playwright** — configuración de una sola vez (`npm install -D @playwright/test` + `npx playwright install chromium`). La app también lo ofrece automáticamente la primera vez que ejecutas.
- **Abrir carpeta**, **Eliminar**, **Actualizar**.

### Grabar

- **Nombre sesión** y **Proyecto** opcionales (desplegable de proyectos existentes, o escribe uno nuevo).
- Idioma, micrófono, objetivo de captura y captura inteligente opcional.
- Cuenta atrás 3‑2‑1 y graba hasta que lo detengas. Al detener, el nombre y el proyecto se guardan automáticamente.

---

## Contexto del proyecto — enseñarle a la IA sobre tu producto

Unas capturas genéricas solo le dicen a la IA *qué pasó*, no *qué es tu producto*. El **contexto del proyecto** resuelve eso.

Cada proyecto tiene un documento Markdown editable que describe qué es la aplicación, cómo funciona, sus roles, sus reglas de negocio y qué cabe esperar. Este texto se antepone al prompt en **cada** generación de ese proyecto, así que la IA produce resultados anclados en tu realidad en vez de adivinar.

**Editarlo:** Mis sesiones → selecciona una sesión que tenga proyecto → **Contexto del proyecto** → escribe/guarda. (Si la sesión no tiene proyecto, asígnaselo antes con **Renombrar**.)

Ejemplo:

```markdown
# Proyecto: Portal Clientes

Un portal B2B para gestionar cuentas de clientes.
- El login es email + contraseña; el SSO no está activado en test.
- Roles: **admin** (acceso total) y **usuario** (solo lectura en facturación).
- "Impersonar" permite a un admin actuar como usuario — se espera un banner amarillo mientras dura.
- Las formulaciones necesitan al menos un componente antes de poder guardarse.
```

Con eso puesto, una generación de "Reporte de bug" o "Casos de prueba" usará la terminología correcta, sabrá qué comportamientos son los esperados y señalará las desviaciones con más precisión.

---

## Testing exploratorio

La sección **Testing exploratorio** analiza una sesión como lo haría un tester exploratorio senior, y está escrita para ser **conocimiento reutilizable del proyecto**:

- **Charter** — qué área/funcionalidad se exploró y por qué.
- **Áreas y funcionalidades observadas** — pantallas, flujos, elementos y cómo se comportan.
- **Observaciones** — comportamientos, estados, validaciones y mensajes destacables (solo basados en evidencia).
- **Riesgos y posibles problemas** — zonas frágiles o dudosas (`[UNCLEAR]` cuando no se puede verificar).
- **Cobertura y siguientes pruebas sugeridas** — huecos y qué explorar a continuación.

**El bucle que hace a la IA más lista con el tiempo:** genera la sección exploratoria y luego, en la pestaña **Reporte**, pulsa **➕ Añadir al contexto**. Las notas se añaden al contexto del proyecto, así que las generaciones futuras de ese proyecto ya conocen lo que la exploración descubrió. Haz unas cuantas sesiones exploratorias y el contexto del proyecto se convierte en una base de conocimiento viva.

---

## Secciones del reporte

Elige cualquier combinación en la pestaña **Resumen**. Las secciones siempre se renderizan en un orden lógico de arriba abajo.

| Sección | Qué produce |
|---|---|
| **Resumen / Explicación** | 2–4 frases: qué se probó, el flujo y el resultado |
| **Pasos para reproducir** | Lista numerada y limpia de pasos en imperativo |
| **Testing exploratorio** | Charter, áreas, observaciones, riesgos, cobertura (ver arriba) |
| **Casos de prueba** | Un bloque por caso: objetivo, precondiciones, los criterios de aceptación que verifica y una tabla Paso / Resultado esperado / Resultado obtenido / Estado. Un caso de prueba agrupa varios pasos — no es un caso por acción. Con los criterios del ticket pegados, cierra con una tabla de cobertura |
| **Plan de pruebas** | Tabla Paso / Acción / Esperado / Estado (las acciones se construyen de forma determinista a partir de eventos reales) |
| **Reporte de bug** | Resumen, severidad, pasos de reproducción, esperado vs. real |
| **Ticket Jira** | Ticket listo para Jira (título, tipo, prioridad, etiquetas, descripción, reproducción, esperado/real) |

Todos los reportes terminan además con un **recorrido visual**: una captura por paso.

El reporte lo terminas tú:

- **Editar** abre el Markdown del reporte para modificarlo — corregir un estado, reescribir un caso, añadir una nota — y **Guardar** lo escribe de vuelta. Mientras editas, las capturas se reducen a marcadores cortos `![alt](img://N)` (un reporte es casi todo base64) y se restauran al guardar; borra un marcador para quitar esa captura.
- **+ Test cases** añade casos nuevos y sin duplicados a un reporte existente. La casilla de al lado elige cuántos (1–20), y la elección se recuerda.

---

## Scripts de automatización profesionales

Los scripts se generan de forma **determinista** (sin IA) a partir de los eventos capturados, y siguen las buenas prácticas de Playwright para que se lean como código escrito a mano y listo para revisión:

- `@playwright/test` con un bloque `test.describe(<proyecto>)` y un título `test(<nombre de la sesión>)` con sentido.
- Cada acción envuelta en `test.step(...)` para trazas legibles.
- **Locators orientados al usuario y con auto-espera**, en este orden de preferencia: `getByRole` → `getByLabel` → `getByPlaceholder` → `getByText` → `locator(css)`.
- **Aserciones web-first**: `await expect(page).toHaveURL(...)` tras navegar, `await expect(field).toHaveValue(...)` tras escribir.
- **Sin esperas fijas** — Playwright espera automáticamente.
- Las acciones basadas solo en coordenadas (apps de escritorio o elementos sin nombre accesible) se convierten en pasos **TODO** claramente marcados en vez de clics por píxel frágiles.

> La calidad del script refleja la calidad de la captura: **las sesiones web grabadas con la extensión de navegador producen locators reales**; los pasos solo de escritorio se convierten en TODOs que puedes completar.

**Credenciales y URL de test — nunca en el código.** Las contraseñas *nunca* se capturan (por diseño), así que los specs generados leen las credenciales de variables de entorno en tiempo de ejecución: `QA_BASE_URL`, `QA_USERNAME`, `QA_PASSWORD`. Configúralas en **Mis scripts → 🔐 Credenciales de test** (escribe `qa-scripts/.env`, que está en el `.gitignore` y lo carga automáticamente `playwright.config.ts`):

- Los campos de contraseña se convierten en `fill(process.env.QA_PASSWORD ?? '')` — el secreto nunca toca el `.spec.ts`.
- Los campos de email/usuario se convierten en `process.env.QA_USERNAME ?? '<valor capturado>'` — sobrescribible por entorno.
- El spec siempre abre la aplicación (desde la primera URL capturada, o `QA_BASE_URL` si no hay ninguna) **antes** de la primera acción, así nunca se queda en `about:blank`.

**¿Empezaste a grabar ya con la sesión iniciada? Usa un login guardado.** Si una sesión se grabó *después* del login, su spec no tiene pasos de login, así que un navegador nuevo aterriza en la pantalla de acceso. Inicia sesión una vez y reutiliza esa sesión en todos los specs (`storageState` de Playwright):

```powershell
cd qa-scripts
npx playwright test --project=setup     # inicia sesión con QA_* y guarda .auth/state.json
```

`auth.setup.ts` (creado automáticamente) inicia sesión con `QA_USERNAME` / `QA_PASSWORD` contra `QA_LOGIN_URL` (o `QA_BASE_URL`); ajusta sus locators si no coinciden con tu formulario de login. A partir de ahí, todos los `*.spec.ts` arrancan autenticados. `.auth/` está en el `.gitignore`.

**Generar:** marca **Script Playwright** al generar un reporte (pestaña Resumen). El spec se archiva en `qa-scripts/<proyecto>/<nombre>-<id>.spec.ts` y aparece en **Mis scripts**.

**Ejecutar desde la app:** Mis scripts → selecciona → **▶ Ejecutar**. La primera vez, acepta la instalación única de Playwright. Se abre un navegador visible y los pasos se ejecutan ralentizados para que puedas verlos.

**Ejecutar desde una terminal** (equivalente):

```powershell
cd qa-scripts
npm install -D @playwright/test        # solo la primera vez
npx playwright install chromium        # solo la primera vez
npx playwright test --headed <proyecto>/<archivo>.spec.ts
```

`qa-scripts/playwright.config.ts` se crea automáticamente (modo visible, `slowMo`, un solo worker, reporter `list`). Los archivos `.spec.ts` se pueden subir al repositorio sin problema; `node_modules/`, `test-results/` y `playwright-report/` están en el `.gitignore`.

---

## Proveedores de IA

### IA local con Ollama

Ejecuta la inferencia enteramente en tu propia GPU — sin clave de API, sin internet.

```powershell
# 1. Instala Ollama desde https://ollama.com/download y ábrelo
# 2. Descarga un modelo con visión
ollama pull qwen2.5vl:7b          # modelo de visión de 7B (recomendado por defecto)
ollama pull llama3.2-vision:11b   # modelo de visión de 11B
# 3. Ollama sirve en http://localhost:11434 automáticamente
```

En la app: abre una sesión → **Resumen** → proveedor **Local (Ollama)** → **Probar conexión** (rellena la lista de modelos) → **Generar Documentación**. No hace falta `ANTHROPIC_API_KEY`.

> **Nota sobre Docker:** `docker-compose.yml` pasa `host.docker.internal` para que el contenedor llegue a Ollama en el host (con un fallback `host-gateway` en Linux).

**Rendimiento local y VRAM** — la generación usa la API nativa de Ollama con una ventana de contexto limitada para no salirse de la VRAM:

| Variable | Por defecto | Efecto |
|----------|---------|--------|
| `OLLAMA_NUM_CTX`   | `8192` | Ventana de contexto. Bájala (p. ej. `4096`) si se desborda a CPU; súbela si tienes más VRAM. |
| `MAX_IMAGES_LOCAL` | `5`    | Capturas enviadas al modelo. Menos = más rápido en CPU. |
| `OLLAMA_TIMEOUT`   | `900`  | Segundos máximos de espera para la inferencia local. |
| `OLLAMA_KEEP_ALIVE`| `30m`  | Cuánto mantiene Ollama el modelo + su caché de prefijo en memoria (reutilizada entre generaciones de una sesión). Más tiempo = repeticiones más rápidas, más VRAM ocupada. |

> **Nota sobre GPU:** Ollama usa tu GPU solo con el soporte correspondiente de ROCm (AMD) / CUDA (NVIDIA). Las GPUs muy nuevas necesitan una build reciente de Ollama (p. ej. AMD RDNA 4 / RX 9000 `gfx1201` desde Ollama 0.30+). Actualiza con `winget upgrade --id Ollama.Ollama`; verifícalo con `curl http://localhost:11434/api/ps` (`size_vram` debería ser > 0). Los proveedores en la nube no se ven afectados.

### Groq / Gemini (nube gratuita)

1. Consigue una clave (Groq: <https://console.groq.com>; Gemini: <https://aistudio.google.com>).
2. Añádela a `.env` (`GROQ_API_KEY=` / `GEMINI_API_KEY=`).
3. `docker compose up -d --force-recreate`.
4. En la app, selecciona el proveedor y un modelo, y genera. (Gemini y Ollama admiten **Probar conexión** para listar los modelos en vivo.)

### Anthropic Claude

Añade `ANTHROPIC_API_KEY` a `.env`, recrea el contenedor y elige **Anthropic (Claude)**. El modelo por defecto es un modelo Claude actual; las imágenes se reducen automáticamente para respetar los límites del proveedor, y el *adaptive thinking* se gestiona por ti.

**El contexto del proyecto se cachea en el prompt para reducir coste.** El contexto de cada proyecto es idéntico en todas las secciones y en todas las regeneraciones, así que se envía como **prefijo cacheable** en vez de facturarse de nuevo cada vez — en Anthropic se convierte en un bloque `system` con `cache_control` a un **TTL de 1 hora** (`ANTHROPIC_CACHE_TTL`), de modo que las generaciones repetidas lo leen a ~10 % del precio de entrada. Esa misma colocación de prefijo estable permite que **Gemini 2.5** lo cachee de forma implícita y que **Ollama** reutilice su caché KV local; **Groq** no tiene caché, pero no se ve afectado. Si el proveedor llegara a rechazar las opciones de caché, la generación pasa de forma transparente a enviar el contexto en línea.

---

## Arquitectura

- El **agente** y la **app de escritorio** se ejecutan de forma **nativa** en el host (necesitan acceso a pantalla/teclado/micrófono). *No* están contenerizados.
- El **backend** corre en Docker, enlazado a `127.0.0.1:8000`, en un bridge solo de salida.
- **Volumen compartido**: el `qa-sessions/` del host se monta dentro del contenedor de la API para que pueda leer eventos/capturas y escribir los metadatos de sesión de vuelta en `manifest.json`.
- **Persistencia**: el volumen Docker `qa-data` guarda `sessions.db` (SQLite: sesiones + contexto por proyecto) y los reportes generados.
- Los **scripts** viven en el host bajo `qa-scripts/` y los genera/ejecuta la app de escritorio (Node/Playwright se ejecutan en el host para que pueda abrirse un navegador real).

---

## Estructura del proyecto

```
FullQA.ai/
├── .env.example            # Plantilla — cópiala a .env y pon tu(s) clave(s)
├── .gitignore              # Excluye .env, qa-sessions/, qa-scripts/node_modules/, *.wav …
├── docker-compose.yml      # Solo el servicio API; puerto solo en localhost; qa-sessions montado
├── requirements.txt        # Dependencias del agente y la UI de escritorio
├── build.ps1               # PyInstaller → dist\FullQA.ai.exe
│
├── agent/                  # Agente del host (nativo, NO en Docker)
│   ├── main.py             # Punto de entrada CLI + bandeja
│   ├── session.py          # Ciclo de vida de la sesión → qa-sessions/YYYY-MM-DD/{uuid}/
│   ├── capture.py          # Eventos de pynput + capturas con mss
│   ├── audio.py            # sounddevice + transcripción con faster-whisper
│   ├── watcher.py          # captura inteligente (IA) opcional
│   ├── weblistener.py      # endpoint local para la extensión de navegador
│   └── tray.py             # UI de la bandeja del sistema
│
├── desktop/
│   └── ui.py               # App PyQt6: Mis sesiones / Mis scripts / Grabar,
│                           #   editor de contexto de proyecto, visor de reportes, i18n (ES/EN)
│
├── services/
│   └── api/                # Backend FastAPI (Docker)
│       └── app/
│           ├── main.py           # Endpoints REST (sesiones, meta, proyectos, playwright…)
│           ├── claude_gen.py     # IA multiproveedor + agrupación de eventos + secciones
│           ├── playwright_gen.py # Generación determinista y profesional de Playwright
│           └── database.py       # SQLite: sesiones + contexto por proyecto
│
├── extension/              # Extensión de navegador opcional (selectores web reales)
│
├── qa-sessions/            # Autocreada, en .gitignore — sesiones grabadas
│   └── YYYY-MM-DD/{uuid}/
│       ├── manifest.json   #   incl. nombre + proyecto
│       ├── events.jsonl
│       ├── screenshots/*.png
│       ├── audio.wav       #   (si --audio)
│       └── transcript.txt  #   (si --audio)
│
└── qa-scripts/             # Autocreada — specs de Playwright generados
    ├── playwright.config.ts    #   scaffold con navegador visible + slowMo
    ├── package.json
    └── <proyecto>/*.spec.ts    #   agrupados por proyecto (node_modules/ en .gitignore)
```

---

## Formatos de datos

### `manifest.json`

```json
{
  "session_id":       "uuid",
  "started_at":       "2026-05-04T12:00:00Z",
  "ended_at":         "2026-05-04T12:05:00Z",
  "os":               "win",
  "language":         "es",
  "audio_enabled":    false,
  "event_count":      47,
  "screenshot_count": 12,
  "name":             "Login con credenciales inválidas",
  "project":          "Portal Clientes"
}
```

### `events.jsonl` — un objeto JSON por línea

```json
{"ts": "2026-05-04T12:00:00.123456Z", "type": "click", "x": 640, "y": 400, "selector": "#login", "control": "button", "element": "Sign in", "screenshot": "…_click.png"}
{"ts": "2026-05-04T12:00:01.000000Z", "type": "key",   "text": "user@example.com", "selector": "#email", "control": "textbox", "element": "Email"}
```

Cuanto más ricos sean los campos capturados (`selector`, `control`, `element`), mejores serán tanto la documentación de la IA como los locators de Playwright generados.

---

## Referencia de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/health` | Sonda de vida |
| `GET`  | `/providers/ollama/models` | Modelos de Ollama instalados + conectividad |
| `GET`  | `/providers/gemini/models` | Modelos de Gemini disponibles |
| `GET`  | `/sessions` | Lista todas las sesiones (BD + sistema de archivos) |
| `GET`  | `/sessions/{id}` | Detalle de la sesión |
| `POST` | `/sessions/{id}/ingest` | Registra una sesión desde el volumen compartido |
| `POST` | `/sessions/{id}/meta` | Define el **nombre** y el **proyecto** de la sesión |
| `POST` | `/sessions/{id}/generate` | Lanza la generación asíncrona del reporte (secciones, proveedor, modelo) |
| `POST` | `/sessions/{id}/report/more-cases` | Añade N casos de prueba nuevos |
| `GET`  | `/sessions/{id}/report` | Obtiene el reporte Markdown generado |
| `PUT`  | `/sessions/{id}/report` | Sobrescribe el reporte con Markdown editado |
| `GET`  | `/sessions/{id}/events` | Eventos parseados |
| `GET`  | `/sessions/{id}/screenshots/{file}` | Sirve un PNG de captura |
| `GET`  | `/sessions/{id}/playwright` | Genera un spec de Playwright profesional |
| `DELETE` | `/sessions/{id}` | Elimina una sesión (BD + reporte + archivos) |
| `GET`  | `/projects` | Lista los nombres de proyecto conocidos |
| `GET`  | `/projects/{name}/context` | Obtiene el contexto de un proyecto |
| `PUT`  | `/projects/{name}/context` | Define el contexto de un proyecto |

Documentación interactiva: `http://localhost:8000/docs`

---

## Seguridad

| Control | Implementación |
|---------|---------------|
| Puertos | La API se enlaza a `127.0.0.1:8000` — nunca a `0.0.0.0` |
| Aislamiento de red | El contenedor de la API está en un bridge solo de salida; sin exposición entrante |
| Secretos | Las claves de API se leen solo de variables de entorno; nunca están escritas en el código. `.env` está en el `.gitignore`; mantén las claves reales **fuera** de `.env.example`. Un hook de pre-commit bloquea los commits de `.env` y las claves `sk-ant-` en bruto en los diffs |
| Usuario del contenedor | Corre sin root (`qauser`, UID 1000) |
| Montaje de volumen | `qa-sessions/` se monta en lectura-escritura (la API reescribe los metadatos en `manifest.json`); los IDs de sesión se validan para rechazar `/`, `\`, `..` |
| Residencia de los datos | Con Ollama no sale nada de la máquina; en el resto de casos solo se envía al proveedor elegido la sesión sobre la que generas |

> Si alguna vez una clave real acaba en un archivo commiteado, **rótala** en el proveedor y elimínala del historial.

---

## Solución de problemas

**"API Offline" en la app**
→ `docker compose up -d` y espera ~15 s al health check. Si acabas de editar `.env`, usa `--force-recreate`.

**Claude dice "no API key" aunque está en `.env`**
→ El contenedor se arrancó antes de definir la clave. Ejecuta `docker compose up -d --force-recreate`.

**Error 404 de modelo (p. ej. `model: claude-…` not found)**
→ El modelo fijado fue retirado. La app trae IDs de modelo actuales; si fijaste uno antiguo, elige un modelo actual en el desplegable.

**El test de Playwright abre `about:blank` / falla el login**
→ La sesión no tenía URL capturada, o falta la contraseña (que nunca se captura). Abre **Mis scripts → 🔐 Credenciales de test**, define `QA_BASE_URL`, `QA_USERNAME` y `QA_PASSWORD`, y vuelve a generar el script. Las sesiones web grabadas **con la extensión de navegador** capturan las URLs reales automáticamente.

**Playwright: "No tests found"**
→ Corregido — las rutas de los scripts se pasan con barras normales. Actualiza y vuelve a ejecutar. Si lo lanzas a mano, haz `cd qa-scripts` primero.

**Mis scripts → Ejecutar no hace nada / da errores de Playwright**
→ Pulsa **Instalar Playwright** una vez (necesita Node.js 18+ en el PATH) y vuelve a ejecutar.

**Error de imagen: "dimensions exceed max allowed size"**
→ Corregido — las capturas se reducen antes de enviarse. Reconstruye el backend si estás en una build antigua.

**`python` no encontrado (Windows)**
→ Usa `.\.venv\Scripts\python.exe`, o instala Python con `uv`.

**No aparece el icono de bandeja**
→ Algunos entornos necesitan `pywin32`: `uv pip install pywin32`, y relanza.

**Capturas en negro/vacías (macOS)**
→ Concede permiso de Grabación de Pantalla a tu terminal en Ajustes del Sistema → Privacidad y Seguridad.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
