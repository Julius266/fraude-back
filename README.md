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

## 🌟 Características Principales

1. **Ingestión Inteligente de Gmail:** Ingestión en tiempo real mediante notificaciones Pub/Sub o escaneos manuales. El motor normaliza el texto, filtra spam y detecta palabras de intención de reclamos.
2. **Ciclo de Auto-Respuesta Resiliente:** Si un cliente expresa intención de reportar un siniestro pero no adjunta la documentación oficial, el sistema le responde en segundos adjuntando la plantilla formal y creando un hilo de conversación de seguimiento.
3. **Mapeo y Parseo de Adjuntos (DOCX, PDF, TXT):**
   * **Archivos TXT:** Lectura directa ultrarrápida.
   * **Archivos PDF:** Extracción de texto estructurado nativo y procesamiento de imágenes con **OCR** (Tesseract) si el PDF es escaneado.
   * La IA analiza la estructura del documento y extrae con precisión matemática los **20 campos del modelo de base de datos**.
4. **Motor de Scoring de Fraude Dual:**
   * **Reglas Deterministas:** Validaciones basadas en límites de negocio (saturación de montos, vigencia de pólizas, sucursales sospechosas).
   * **IA Generativa (OpenAI GPT):** Análisis semántico y lingüístico del relato del cliente para detectar incoherencias, similitudes sospechosas y patrones de fraude.
5. **Copiloto AI con RAG (Retrieval-Augmented Generation):** Indexación automática de los siniestros en vectores. El analista puede preguntar en lenguaje natural sobre cualquier siniestro en el dashboard y el copiloto responderá citando los siniestros relevantes como contexto.

---

## 📂 Sistema de Plantillas de Siniestro

El backend cuenta con un sistema flexible para adjuntar archivos oficiales en la auto-respuesta. El directorio designado es:
📁 **`storage/templates/`**

### Formatos Soportados (Orden de Prioridad):
El backend busca automáticamente en la carpeta y adjunta el formato de mayor calidad disponible:
1. **`plantilla_siniestro.docx` (Word):** Si existe, se enviará como archivo Word adjunto.
2. **`plantilla_siniestro.pdf` (PDF):** Si no hay Word, pero existe este PDF, se enviará el PDF.
3. **`plantilla_siniestro.txt` (Texto Fallback):** Si no hay ninguno, el backend genera dinámicamente un archivo `.txt` para evitar que el flujo se detenga.

> [!TIP]
> **Ubicación Física:** Coloca tus plantillas de marca corporativa Aseguradora del Sur en `fraude-back/storage/templates/`. El sistema las detectará de inmediato sin reiniciar el servidor.

---

## 📋 Requisitos Previos

Asegúrate de contar con las siguientes tecnologías e integraciones instaladas y configuradas:

| Componente | Requerimiento | Descripción / Ubicación |
| :--- | :--- | :--- |
| **Python** | Versión 3.11 o superior | Intérprete oficial para ejecutar el backend. |
| **PostgreSQL** | Local o en la nube (Neon.tech) | Base de datos relacional para guardar siniestros y estados. |
| **Credenciales Google** | `credentials.json` | Archivo de credenciales de escritorio descargado desde Google Cloud Console. |
| **Token de Acceso** | `token.json` | Generado automáticamente en el navegador durante el primer inicio de sesión de Gmail. |
| **Google Pub/Sub** | `GMAIL_WATCH_TOPIC` | Tópico para recibir alertas de nuevos correos en tiempo real. |
| **OpenAI Key** | `OPENAI_API_KEY` | API Key de OpenAI para el análisis de riesgo IA y el Chat Copiloto RAG. |

---

## ⚙️ Configuración de Variables de Entorno (`.env`)

Crea un archivo `.env` en la raíz de la carpeta `fraude-back/` basándote en `.env.example`:

```env
APP_NAME=ShieldMind Backend
APP_ENV=development
API_V1_STR=/api/v1
APP_BASE_URL=http://127.0.0.1:8000
FRONTEND_URL=http://localhost:3000

# Base de Datos (PostgreSQL)
DATABASE_URL=postgresql+psycopg2://fraude_user:fraude_pass@localhost:5432/fraude_back
# NOTA: Si usas Neon.tech u otro proveedor remoto con SSL, añade ?sslmode=require al final.

# Configuración Gmail
GMAIL_CLIENT_SECRET_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
GMAIL_DOWNLOAD_DIR=storage/gmail_attachments
GMAIL_WATCH_TOPIC=projects/tu-proyecto-google/topics/tu-topico-gmail
GMAIL_KEYWORDS=SINIESTRO,RECLAMO

# Configuración OpenAI e IA
OPENAI_API_KEY=tu_openai_api_key_aqui
OPENAI_MODEL=gpt-4
EMBEDDING_MODEL=text-embedding-3-small
```

---

## 🚀 Inicio Rápido (Comandos de Ejecución)

Sigue estos sencillos pasos en tu consola de PowerShell (en Windows):

### 1. Preparar el Entorno Virtual e Instalar Dependencias
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

# Instalar los paquetes y dependencias del sistema
pip install -r requirements.txt
```

### 2. Ejecutar Migraciones de Base de Datos
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
# Levanta el backend estrictamente en http://127.0.0.1:8000
.\scripts\dev-up.ps1
```

Si deseas iniciarlo de manera manual:
```powershell
# Inicio manual con recarga en caliente (Hot Reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 🔍 Referencia de Endpoints y Documentación Interactiva

Una vez que el servidor backend esté corriendo, puedes acceder a la documentación interactiva desde tu navegador:
*   🛡️ **Swagger UI:** [http://127.0.0.1:8000/swagger](http://127.0.0.1:8000/swagger)
*   🧠 **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

### Principales Endpoints de Integración:

| Módulo | Tipo | Endpoint | Descripción |
| :--- | :--- | :--- | :--- |
| **Siniestros** | `GET` | `/api/v1/siniestros` | Lista todos los siniestros con paginación. |
| **Siniestros** | `POST` | `/api/v1/siniestros/{id}/score/ai` | Evalúa reglas de fraude + análisis cognitivo OpenAI. |
| **Gmail** | `POST` | `/api/v1/gmail/scan` | Escanea manualmente la bandeja de entrada de Gmail. |
| **Webhooks** | `POST` | `/api/v1/webhooks/gmail/push` | Recibe la notificación Push de Google Pub/Sub. |
| **Copiloto RAG** | `POST` | `/api/v1/chat/index` | Indexa los nuevos siniestros a la base vectorial. |
| **Copiloto RAG** | `POST` | `/api/v1/chat/query` | Realiza consultas en lenguaje natural al Copiloto AI. |

---

## 🛠️ Diagnóstico y Resolución de Problemas (FAQ)

> [!WARNING]
> **Error de Sintaxis al levantar Uvicorn:**
> Si al levantar el servidor ves errores del tipo `SyntaxError: '(' was never closed` o similar, asegúrate de no tener bloques duplicados en el código. *Este backend ha sido saneado de raíz y ya no posee errores de compilación.*

> [!IMPORTANT]
> **Error `AttributeError: 'GmailIngestionService' object has no attribute '_send_auto_reply_template'`:**
> Este error ocurre cuando la firma del método de auto-respuesta se borra de `service.py`. En la versión actual este problema está **100% corregido** y restaurado con una estructura limpia.

> [!CAUTION]
> **Fallo de lectura de adjunto TXT en Reprocesamiento (`invalid pdf header`):**
> Si subes o respondes con una plantilla `.txt`, la función de reprocesamiento histórico solía asumir erróneamente que todos los adjuntos eran PDFs. Hemos modificado la función `reprocess_correo_pdfs` para que valide la extensión `.txt` y la procese de forma inmediata como texto plano, ahorrando tiempo y eliminando la advertencia de error.
