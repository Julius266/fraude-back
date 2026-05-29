# fraude-back — ShieldMind API

Backend en **FastAPI** para **ShieldMind AI** (Aseguradora del Sur): ingesta de correos Gmail, extracción de siniestros desde PDFs, **scoring antifraude** y **copiloto RAG** para analistas.

| Entorno | URL |
|---------|-----|
| Producción | https://fraude-back-production.up.railway.app |
| Swagger | https://fraude-back-production.up.railway.app/swagger |
| Frontend | https://fraude-front.vercel.app |

---

## Tabla de contenidos

1. [Qué hace el sistema](#qué-hace-el-sistema)
2. [Stack y arquitectura](#stack-y-arquitectura)
3. [Estructura del proyecto](#estructura-del-proyecto)
4. [Requisitos](#requisitos)
5. [Inicio rápido (local)](#inicio-rápido-local)
6. [Variables de entorno](#variables-de-entorno)
7. [Autenticación Gmail (OAuth)](#autenticación-gmail-oauth)
8. [Módulos principales](#módulos-principales)
9. [Referencia de API](#referencia-de-api)
10. [Scoring antifraude](#scoring-antifraude)
11. [Plantillas de correo](#plantillas-de-correo)
12. [Scripts útiles](#scripts-útiles)
13. [Despliegue](#despliegue)
14. [Problemas frecuentes](#problemas-frecuentes)
15. [Documentación adicional](#documentación-adicional)

---

## Qué hace el sistema

Flujo típico de un analista:

```
Login Google (OAuth) → Escaneo Gmail → PDF/TXT en adjuntos
        → Parseo de campos → Siniestro en PostgreSQL
        → Scoring (reglas + IA opcional) → Bandeja en el front
        → Copiloto RAG responde preguntas sobre los casos
```

| Capacidad | Descripción |
|-----------|-------------|
| **Ingestión Gmail** | Busca correos con palabras clave (`SINIESTRO`, `RECLAMO`, …), guarda metadatos y descarga adjuntos. |
| **Parseo de documentos** | Extrae ~20 campos de PDF (texto nativo u OCR), TXT o DOCX hacia el modelo `Siniestro`. |
| **Auto-respuesta** | Si el cliente escribe sin adjunto oficial, puede enviar plantilla de siniestro por Gmail. |
| **Scoring dual** | Reglas deterministas (RS-XX) + análisis OpenAI opcional; semáforo Rojo / Amarillo / Verde. |
| **Copiloto RAG** | Embeddings en PostgreSQL (pgvector); chat en lenguaje natural sobre siniestros indexados. |
| **Multi-usuario** | Cada analista tiene su token OAuth y sus siniestros/correos filtrados por `owner_email`. |
| **Watch Pub/Sub** | Notificaciones push de Gmail para procesar correos nuevos (opcional en producción). |

---

## Stack y arquitectura

| Capa | Tecnología |
|------|------------|
| API | FastAPI, Uvicorn, Pydantic Settings |
| Base de datos | PostgreSQL (Neon en prod) + Alembic |
| Vectores | pgvector (embeddings para chat) |
| Gmail | Google OAuth 2.0, Gmail API, Pub/Sub |
| IA | OpenAI (scoring, chat, embeddings) |
| PDF/OCR | pdfplumber, Tesseract (opcional) |

```
Cliente (Next.js)  ──HTTP/CORS──►  fraude-back (/api/v1)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              PostgreSQL           Gmail API            OpenAI
              (siniestros,         (OAuth por           (score,
               oauth tokens,         analista)            chat,
               embeddings)                               embed)
```

---

## Estructura del proyecto

```text
fraude-back/
├── app/
│   ├── main.py                 # App FastAPI, CORS, Swagger, lifespan
│   ├── api/
│   │   ├── deps.py             # Header X-Analyst-Email, scope por usuario
│   │   ├── owner_scope.py      # Filtros owner_email en consultas
│   │   └── v1/endpoints/
│   │       ├── siniestros.py   # CRUD, scoring, email, status
│   │       ├── gmail.py        # OAuth, scan, correos, watch
│   │       ├── chat.py         # RAG: query, index, sesiones
│   │       └── webhooks.py     # Pub/Sub push de Gmail
│   ├── core/
│   │   ├── config.py           # Settings desde .env
│   │   ├── exceptions.py       # Errores Google API formateados
│   │   └── bootstrap.py        # Arranque / migraciones legacy
│   ├── db/                     # SQLAlchemy session, base
│   ├── models/                 # Siniestro, GmailCorreo, OAuth token, chat…
│   ├── schemas/                # DTOs Pydantic (request/response)
│   └── integrations/
│       ├── gmail/              # OAuth, cliente API, ingestión, service
│       ├── siniestros/         # PDF parser, scoring, IA, plantillas email
│       └── chat/               # Embeddings, vector search, ChatService
├── alembic/                    # Migraciones de BD
├── storage/
│   ├── gmail_attachments/      # PDFs descargados (gitignored)
│   └── templates/              # Plantillas auto-respuesta (docx/pdf/txt)
├── scripts/
│   ├── dev-up.ps1              # Levanta uvicorn en :8000
│   └── railway-deploy.ps1      # Deploy a Railway
├── credentials.json            # OAuth Google Web (local, gitignored)
├── Dockerfile
├── DEPLOY.md                   # Guía Railway + Google Cloud
└── README.md
```

### Qué hace cada carpeta clave

| Ruta | Responsabilidad |
|------|-----------------|
| `app/integrations/gmail/oauth.py` | Flujo OAuth, tokens en BD (`gmail_oauth_tokens`), scopes `gmail.readonly` + `gmail.send`. |
| `app/integrations/gmail/service.py` | Escaneo, auto-respuesta, reprocesar PDFs de un correo. |
| `app/integrations/siniestros/scoring.py` | Motor de reglas RS-XX y puntaje total. |
| `app/integrations/siniestros/auto_scoring.py` | Auditoría automática al crear/actualizar siniestros. |
| `app/integrations/chat/` | Indexación de embeddings y respuestas RAG. |
| `app/api/deps.py` | Exige header `X-Analyst-Email` en rutas protegidas. |

---

## Requisitos

| Componente | ¿Obligatorio? | Para qué |
|------------|---------------|----------|
| Python 3.11+ | Sí | Runtime |
| PostgreSQL / Neon | Sí | Siniestros, tokens OAuth, chat, vectores |
| `credentials.json` (OAuth **Web**) | Para Gmail | Login y escaneo de bandeja |
| `OPENAI_API_KEY` | Recomendado | Scoring IA + copiloto + embeddings |
| `GMAIL_WATCH_TOPIC` | Opcional | Push en tiempo real vía Pub/Sub |
| Tesseract | Opcional | OCR en PDFs escaneados |

---

## Inicio rápido (local)

### 1. Clonar e instalar

```powershell
cd D:\work\fraude-back
python -m venv .venv          # solo la primera vez
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configurar entorno

Crea `.env` en la raíz (usa los valores de ejemplo abajo). Coloca `credentials.json` (cliente OAuth **Web** de Google Cloud).

### 3. Base de datos

```powershell
alembic upgrade head
```

### 4. Arrancar API

```powershell
.\scripts\dev-up.ps1
```

Abre **http://127.0.0.1:8000/swagger**.

Para detener:

```powershell
.\scripts\dev-down.ps1
```

### URLs locales útiles

| URL | Uso |
|-----|-----|
| http://127.0.0.1:8000/swagger | Probar endpoints |
| http://127.0.0.1:8000/health | Health check |
| http://127.0.0.1:8000/api/v1/gmail/config | Ver redirect OAuth activo |

---

## Variables de entorno

| Variable | Descripción | Ejemplo local |
|----------|-------------|---------------|
| `APP_ENV` | `development` o `production` (afecta CORS regex Vercel) | `development` |
| `APP_BASE_URL` | URL pública del API | `http://127.0.0.1:8000` |
| `FRONTEND_URL` | Front para redirect post-OAuth | `http://localhost:3000` |
| `ALLOWED_ORIGINS` | Orígenes CORS separados por coma | `http://localhost:3000` |
| `DATABASE_URL` | PostgreSQL (Neon: añade `?sslmode=require`) | `postgresql+psycopg2://...` |
| `GMAIL_CLIENT_SECRET_FILE` | Ruta al JSON OAuth | `credentials.json` |
| `GMAIL_TOKEN_FILE` | Legacy; prod usa BD + `/data/token.json` | `token.json` |
| `GMAIL_OAUTH_REDIRECT_URI` | Callback OAuth (auto si local) | `http://127.0.0.1:8000/api/v1/gmail/auth/callback` |
| `GMAIL_DOWNLOAD_DIR` | Carpeta de adjuntos | `storage/gmail_attachments` |
| `GMAIL_WATCH_TOPIC` | Tópico Pub/Sub completo | `projects/.../topics/...` |
| `GMAIL_KEYWORDS` | Palabras en asunto/cuerpo | `SINIESTRO,RECLAMO` |
| `OPENAI_API_KEY` | Key OpenAI | `sk-...` |
| `OPENAI_MODEL` | Modelo chat/scoring | `gpt-4.1` |
| `EMBEDDING_MODEL` | Modelo embeddings | `text-embedding-3-small` |
| `ENABLE_PDF_OCR` | OCR en PDFs imagen | `true` |

En **Railway**, muchas variables van en `.env.despliegue` y se suben con el script de deploy. Ver [DEPLOY.md](./DEPLOY.md).

---

## Autenticación Gmail (OAuth)

### Flujo

1. El front llama `GET /api/v1/gmail/auth/url?returnTo=/`
2. El usuario autoriza en Google
3. Google redirige a `{APP_BASE_URL}/api/v1/gmail/auth/callback`
4. El backend guarda tokens en `gmail_oauth_tokens` y redirige al front:  
   `{FRONTEND_URL}/login?gmail=connected&email=...`

### Header requerido

Tras login, el front envía en cada petición:

```http
X-Analyst-Email: analista@gmail.com
```

El backend filtra siniestros y correos por ese email.

### Permitir login de cualquier Gmail

En Google Cloud → **Pantalla de consentimiento OAuth**:

1. Completa nombre, email de soporte y **política de privacidad** (URL pública)
2. Pulsa **Publicar aplicación** (pasar de *Testing* → *In production*)

En modo Testing solo entran los **usuarios de prueba** (máx. 100).

Con scopes Gmail, los usuarios verán *“Google hasn't verified this app”* → **Avanzado → Continuar** hasta completar verificación oficial.

Detalle de URIs y Railway: [DEPLOY.md § Google Cloud](./DEPLOY.md#google-cloud--oauth-web).

---

## Módulos principales

### Gmail (`/api/v1/gmail`)

| Función | Endpoint |
|---------|----------|
| Estado OAuth del analista | `GET /auth/status` |
| URL para iniciar login | `GET /auth/url` |
| Callback (solo Google) | `GET /auth/callback` |
| Cerrar sesión Gmail | `POST /auth/logout` |
| Escanear bandeja | `POST /scan` |
| Listar correos guardados | `GET /correos` |
| PDF → siniestros en bandeja | `POST /correos/{id}/procesar` |
| Registrar watch Pub/Sub | `POST /watch/register` |

### Siniestros (`/api/v1/siniestros`)

| Función | Endpoint |
|---------|----------|
| Resumen (totales, por color) | `GET /summary` |
| Listar con score | `GET /` |
| Detalle | `GET /{id}` |
| Crear manual | `POST /` |
| Scoring reglas | `POST /{id}/score` |
| Scoring reglas + IA | `POST /{id}/score/ai` |
| Cambiar estado (dictamen) | `PATCH /{id}/status` |
| Re-auditar casos stale | `POST /reaudit-stale` |
| Enviar correo al asegurado | `POST /{id}/send-email` |
| Eliminar expediente | `DELETE /{id}` |

### Chat RAG (`/api/v1/chat`)

| Función | Endpoint |
|---------|----------|
| Pregunta en lenguaje natural | `POST /query` |
| Indexar embeddings pendientes | `POST /index` |
| Estado de indexación | `GET /index/status` |
| Historial de sesión | `GET /session/{id}/messages` |
| Limpiar sesión | `DELETE /session/{id}` |

### Webhooks (`/api/v1/webhooks`)

| Función | Endpoint |
|---------|----------|
| Push Pub/Sub de Gmail | `POST /gmail/push` |

---

## Scoring antifraude

1. **Reglas (RS-XX)** — Validaciones de negocio: montos, vigencia, documentos, proveedores, etc.
2. **IA (opcional)** — OpenAI analiza narrativa y señales semánticas.
3. **Semáforo** — Puntos → Rojo / Amarillo / Verde (umbrales configurables en front y back).

La auditoría automática corre al ingestar PDFs y en endpoints de re-auditoría. Versión de reglas referenciada en respuestas de scoring.

Archivo de ejemplos de reglas: [`reglas_fraude_ejemplos.md`](./reglas_fraude_ejemplos.md).

---

## Plantillas de correo

Carpeta: **`storage/templates/`**

Prioridad al adjuntar en auto-respuesta:

1. `plantilla_siniestro.docx`
2. `plantilla_siniestro.pdf`
3. Fallback generado: `plantilla_siniestro.txt`

No hace falta reiniciar el servidor al cambiar archivos.

---

## Scripts útiles

| Script | Qué hace |
|--------|----------|
| `scripts/dev-up.ps1` | Mata procesos en :8000 y levanta uvicorn con reload |
| `scripts/dev-down.ps1` | Detiene el backend local |
| `scripts/railway-deploy.ps1` | Sube variables y despliega a Railway |

---

## Despliegue

Guía completa (Railway, Neon, Google OAuth Web, volúmenes, CI):

**→ [DEPLOY.md](./DEPLOY.md)**

Resumen:

- API en **Railway** con Dockerfile
- BD en **Neon**
- OAuth JSON en `GOOGLE_OAUTH_CREDENTIALS_JSON`
- Volumen `/data` para adjuntos y token legacy

---

## Problemas frecuentes

### `redirect_uri_mismatch`

La URI de callback en Google Cloud debe coincidir **exactamente** con `gmail_oauth_redirect_uri` de `/api/v1/gmail/config`.

### `403 access_denied` / “solo testers”

La app OAuth está en **Testing**. Publica la app o agrega el email en usuarios de prueba. Ver [Autenticación Gmail](#autenticación-gmail-oauth).

### `credentials_configured: false` en producción

Falta `GOOGLE_OAUTH_CREDENTIALS_JSON` en Railway o el redeploy no aplicó.

### CORS desde Vercel

En producción: `APP_ENV=production`, `ALLOWED_ORIGINS` con URL del front. También acepta `https://*.vercel.app`.

### Puerto 8000 ocupado

Usa `.\scripts\dev-up.ps1` (libera puertos antes de arrancar).

### Error Google API en JSON

Las respuestas incluyen `"source": "google_api"`. Revisa permisos Gmail API y scopes OAuth.

---

## Documentación adicional

| Documento | Contenido |
|-----------|-----------|
| [DEPLOY.md](./DEPLOY.md) | Railway, variables, OAuth, CI |
| [docs/PLAN_CHAT_RAG.md](./docs/PLAN_CHAT_RAG.md) | Diseño del copiloto RAG |
| [docs/EMBEDDINGS_PGVECTOR.md](./docs/EMBEDDINGS_PGVECTOR.md) | Embeddings y pgvector |
| [AGENTS.md](./AGENTS.md) | Notas para agentes / Docker compose |

---

## Licencia y uso

Proyecto interno — Aseguradora del Sur / ShieldMind AI.
