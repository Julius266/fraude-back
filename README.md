# fraude-back

API backend en **FastAPI** para:

- Ingestión de correos de **Gmail** (watch Pub/Sub, escaneo manual, adjuntos PDF).
- Persistencia de **siniestros** extraídos de PDFs.
- **Scoring de fraude** por reglas y con **OpenAI** (opcional).

Ejecución **local con Python** (sin Docker).

---

## Requisitos

| Componente | Obligatorio | Notas |
|------------|-------------|--------|
| Python 3.11+ | Sí | |
| PostgreSQL o Neon | Sí | URL en `DATABASE_URL` |
| `credentials.json` (Google OAuth) | Para Gmail | Proyecto con Gmail API habilitada |
| `token.json` | Para Gmail | Se genera en el primer uso OAuth |
| Tópico Pub/Sub + `GMAIL_WATCH_TOPIC` | Para push en tiempo real | Mismo `project_id` que `credentials.json` |
| `OPENAI_API_KEY` | Solo scoring IA | |

---

## Inicio rápido

```powershell
# 1. Entrar al proyecto
cd ruta\a\fraude-back

# 2. Entorno virtual (solo la primera vez; si .venv ya existe, omite python -m venv)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Variables de entorno
copy .env.example .env
# Edita .env con tu DATABASE_URL, GMAIL_WATCH_TOPIC, OPENAI_API_KEY, etc.

# 4. Migraciones
alembic upgrade head

# 5. Servidor (recomendado: comando unico que limpia procesos viejos)
.\scripts\dev-up.ps1
```

Abre **http://127.0.0.1:8000/swagger** para probar la API.

En macOS/Linux sustituye la activación del venv por `source .venv/bin/activate`.

---

## Variables de entorno

Copia `.env.example` a `.env`. Archivos sensibles (`.env`, `credentials.json`, `token.json`) están en `.gitignore`.

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `APP_NAME` | Nombre de la app | `fraude-back` |
| `APP_ENV` | Entorno (`development` muestra más detalle en errores) | `development` |
| `API_V1_STR` | Prefijo de la API | `/api/v1` |
| `DATABASE_URL` | Conexión PostgreSQL (SQLAlchemy + psycopg2) | ver abajo |
| `SQLALCHEMY_ECHO` | Log SQL en consola | `false` |
| `GMAIL_CLIENT_SECRET_FILE` | OAuth client secrets | `credentials.json` |
| `GMAIL_TOKEN_FILE` | Token OAuth guardado | `token.json` |
| `GMAIL_DOWNLOAD_DIR` | Carpeta de adjuntos | `storage/gmail_attachments` |
| `GMAIL_WATCH_TOPIC` | Tópico Pub/Sub para Gmail push | `projects/MI_PROYECTO/topics/MI_TOPICO` |
| `GMAIL_KEYWORDS` | Palabras clave (coma) | `SINIESTRO,RECLAMO` |
| `GMAIL_QUERY_HOURS_BACK` | Horas hacia atrás en scan manual | `48` |
| `GMAIL_MAX_RESULTS` | Máximo de mensajes por scan | `50` |
| `ENABLE_PDF_OCR` | OCR en PDFs escaneados | `true` |
| `OPENAI_API_KEY` | API key OpenAI | |
| `OPENAI_MODEL` | Modelo OpenAI | `gpt-4.1` |
| `EMBEDDING_MODEL` | Modelo para embeddings del chat RAG | `text-embedding-3-small` |
| `CHAT_MODEL` | Modelo para respuestas del chat (opcional) | usa `OPENAI_MODEL` |
| `CHAT_K_RESULTS` | Cantidad de siniestros recuperados por consulta | `8` |
| `CHAT_MAX_HISTORY` | Turnos de historial por sesión | `10` |
| `CHAT_SESSION_TTL_SECONDS` | TTL de sesión de chat en memoria | `1800` |

### Base de datos

**PostgreSQL local:**

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@localhost:5432/fraude_back
```

**Neon (u otro host con SSL):**

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@ep-xxx.neon.tech:5432/nombre_db?sslmode=require
```

### Prioridad de configuración

1. Variables de entorno del sistema (p. ej. `GMAIL_WATCH_TOPIC` en Windows).
2. Archivo `.env` en la raíz del proyecto.

Si cambias `.env`, **reinicia uvicorn** (Ctrl+C y vuelve a ejecutar). `--reload` **no** recarga `.env` automáticamente.

---

## Migraciones (Alembic)

```powershell
.\.venv\Scripts\Activate.ps1
alembic upgrade head
```

Crear migración tras cambiar modelos:

```powershell
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
```

---

## Gmail y Pub/Sub

### 1. OAuth (`credentials.json` + `token.json`)

1. En [Google Cloud Console](https://console.cloud.google.com/), crea o usa un proyecto.
2. Habilita **Gmail API**.
3. Crea credenciales OAuth (tipo aplicación de escritorio) y descárgalas como `credentials.json` en la raíz del repo.
4. La primera llamada a un endpoint de Gmail puede abrir el navegador; se guardará `token.json`.

### 2. Tópico Pub/Sub (`GMAIL_WATCH_TOPIC`)

El valor debe coincidir con el **`project_id`** de `credentials.json`:

```json
"project_id": "fraudia"
```

```env
GMAIL_WATCH_TOPIC=projects/fraudia/topics/fraudia
```

En Google Cloud:

1. **Pub/Sub → Topics → Create topic** (mismo proyecto que OAuth).
2. En el tópico → **Permissions** → agregar principal  
   `gmail-api-push@system.gserviceaccount.com` con rol **Pub/Sub Publisher**.

Si el proyecto del tópico no coincide, la API responde **400** con un mensaje del estilo *Invalid topicName does not match projects/...*.

### 3. Flujo recomendado

```text
1. GET  /api/v1/gmail/config          → verificar topic y rutas en ESTE proceso
2. POST /api/v1/gmail/watch/register  → registrar watch (guarda historyId en BD)
3. POST /api/v1/webhooks/gmail/push   → lo llama Google Pub/Sub (no manual en prod)
4. POST /api/v1/gmail/scan            → escaneo manual (pruebas sin Pub/Sub)
5. GET  /api/v1/gmail/correos         → correos guardados
```

---

## Ejecutar el servidor

Recomendado (evita confusiones con 8001/8002):

```powershell
cd ruta\a\fraude-back
.\scripts\dev-up.ps1
```

Este script:
- libera puertos 8000, 8001 y 8002;
- arranca **solo un** backend en `http://127.0.0.1:8000`;
- evita tener multiples uvicorn al mismo tiempo.

Para detener todo:

```powershell
.\scripts\dev-down.ps1
```

Alternativa manual:

```powershell
cd ruta\a\fraude-back
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Sin activar venv:

```powershell
.\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Documentación interactiva

| URL | Descripción |
|-----|-------------|
| http://127.0.0.1:8000/ | Redirige a Swagger |
| http://127.0.0.1:8000/swagger | Swagger UI |
| http://127.0.0.1:8000/redoc | ReDoc |
| http://127.0.0.1:8000/openapi.json | Esquema OpenAPI |
| http://127.0.0.1:8000/health | Health check |

### Logs y errores

- Los logs se escriben en la **misma terminal** donde corre uvicorn (`INFO`, `ERROR`, tracebacks).
- Las respuestas de error suelen ser JSON: `{ "detail": "..." }`.
- Errores de Google API incluyen `"source": "google_api"`.

---

## Referencia de endpoints

Prefijo base: **`/api/v1`**

### Sistema

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado del servicio |

### Siniestros

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/siniestros/status` | Estado del módulo |
| `GET` | `/siniestros` | Listar siniestros (`limit`, `offset`) |
| `GET` | `/siniestros/{id_siniestro}` | Detalle por ID |
| `POST` | `/siniestros/{id_siniestro}/score` | Scoring por reglas |
| `POST` | `/siniestros/{id_siniestro}/score/ai` | Scoring con IA + reglas |

### Gmail

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/gmail/config` | Config Gmail cargada en este proceso |
| `POST` | `/gmail/watch/register` | Registrar watch en Gmail + guardar `historyId` |
| `POST` | `/gmail/scan` | Buscar correos recientes por palabras clave |
| `GET` | `/gmail/correos` | Listar correos persistidos (`limit`) |

### Webhooks

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/webhooks/gmail/push` | Payload Pub/Sub (base64) desde Google |

### Chat RAG

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/chat/index/status` | Estado de indexación de embeddings (total/indexados/pendientes) |
| `POST` | `/chat/index` | Indexa embeddings pendientes en `siniestros` |
| `POST` | `/chat/query` | Consulta en lenguaje natural sobre siniestros indexados |
| `DELETE` | `/chat/session/{session_id}` | Limpia historial de una sesión de chat |

### Ejemplos (curl / Bruno)

Verificar configuración Gmail:

```http
GET http://127.0.0.1:8000/api/v1/gmail/config
```

Registrar watch:

```http
POST http://127.0.0.1:8000/api/v1/gmail/watch/register
```

Escaneo manual:

```http
POST http://127.0.0.1:8000/api/v1/gmail/scan
```

Consulta de chat:

```http
POST http://127.0.0.1:8000/api/v1/chat/query
Content-Type: application/json

{
  "question": "Cuales son los casos mas riesgosos y por que?",
  "session_id": "demo-analista",
  "k": 8
}
```

---

## Estructura del proyecto

```text
fraude-back/
├── app/
│   ├── main.py                 # FastAPI, Swagger, manejo de errores
│   ├── api/v1/
│   │   ├── router.py
│   │   └── endpoints/
│   │       ├── gmail.py
│   │       ├── siniestros.py
│   │       └── webhooks.py
│   ├── core/
│   │   ├── config.py           # Settings desde .env
│   │   ├── logging_config.py
│   │   └── exceptions.py       # Errores Google API, validación topic
│   ├── db/
│   ├── models/
│   ├── schemas/
│   └── integrations/
│       ├── gmail/              # Cliente OAuth + ingestión
│       └── siniestros/         # PDF, scoring, IA
├── alembic/
├── storage/                    # Adjuntos (gitignored)
├── credentials.json            # OAuth Google (gitignored)
├── token.json                  # Token OAuth (gitignored)
├── .env                        # Config local (gitignored)
├── .env.example
├── requirements.txt
└── README.md
```

---

## Problemas frecuentes

### `Permission denied` al crear `.venv`

El entorno **ya existe**. No ejecutes otra vez `python -m venv .venv`. Usa:

```powershell
.\.venv\Scripts\Activate.ps1
```

Solo recrea `.venv` si lo necesitas: cierra todos los `python.exe`, borra la carpeta `.venv` y vuelve a crearla.

### El API muestra un `GMAIL_WATCH_TOPIC` distinto al de `.env`

Causas habituales:

1. **No guardaste** `.env` (Ctrl+S).
2. **No reiniciaste** uvicorn tras editar `.env`.
3. **Varios servidores** en puertos distintos (8000 y 8001) con configs distintas.
4. Variable de entorno del sistema que **pisa** `.env`.

Solución:

```powershell
# Comprobar qué usa ESTE servidor
GET http://127.0.0.1:8000/api/v1/gmail/config

# Limpiar variable de sesión si existe
Remove-Item Env:GMAIL_WATCH_TOPIC -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

# Un solo uvicorn
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Cerrar procesos en puertos 8000/8001:

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
```

### Error 400: topic debe pertenecer al proyecto `fraudia`

`GMAIL_WATCH_TOPIC` usa otro proyecto (p. ej. `fraude-hackiaton`). Debe ser:

```env
GMAIL_WATCH_TOPIC=projects/<project_id_de_credentials>/topics/<nombre>
```

### Error de base de datos

- Revisa `DATABASE_URL` (host, puerto, usuario, contraseña).
- Neon requiere `?sslmode=require`.
- No uses el puerto **5433** de Docker antiguo; en local suele ser **5432**.

### Swagger en 404

Usa **`/swagger`**, no `/docs`.

### Puerto ocupado

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Y actualiza la URL en Bruno al mismo puerto.

---

## Desarrollo

| Acción | Cómo |
|--------|------|
| Recarga de código | `uvicorn --reload` |
| Ver SQL | `SQLALCHEMY_ECHO=true` en `.env` |
| Nueva migración | `alembic revision --autogenerate -m "..."` |
| Ejecutar desde | Raíz del repo (donde está `app/`) |

---

## Resumen de comandos

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger: **http://127.0.0.1:8000/swagger**
