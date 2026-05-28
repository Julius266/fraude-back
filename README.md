# fraude-back

API backend en **FastAPI** para ingestión de correos (Gmail), gestión de siniestros y scoring de fraude (reglas + OpenAI).

## Requisitos

- **Python 3.11+**
- **PostgreSQL** (local) o base en la nube (p. ej. [Neon](https://neon.tech))
- Opcional para Gmail: `credentials.json` y `token.json` de Google Cloud OAuth
- Opcional para scoring con IA: clave de **OpenAI** en `.env`

## Configuración inicial

### 1. Clonar e instalar dependencias

```powershell
cd c:\Users\luxta\Desktop\fraude-back
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

En macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Variables de entorno

Copia el ejemplo y edita los valores:

```powershell
copy .env.example .env
```

Variables principales:

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | URL de conexión SQLAlchemy/psycopg2 |
| `OPENAI_API_KEY` | Clave para scoring con IA (opcional) |
| `GMAIL_CLIENT_SECRET_FILE` | Ruta al JSON de OAuth de Google (por defecto `credentials.json`) |
| `GMAIL_TOKEN_FILE` | Token OAuth guardado tras el primer login (por defecto `token.json`) |
| `GMAIL_WATCH_TOPIC` | Tópico Pub/Sub para push de Gmail (opcional) |

**PostgreSQL local** (puerto estándar 5432):

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@localhost:5432/fraude_back
```

**Neon u otro host en la nube** (SSL obligatorio):

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@tu-host.neon.tech:5432/nombre_db?sslmode=require
```

> No subas `.env`, `credentials.json` ni `token.json` al repositorio (ya están en `.gitignore`).

### 3. Migraciones de base de datos

Con el venv activado y `DATABASE_URL` correcto en `.env`:

```powershell
alembic upgrade head
```

Para crear una nueva migración tras cambiar modelos:

```powershell
alembic revision --autogenerate -m "descripcion_del_cambio"
alembic upgrade head
```

### 4. Gmail (opcional)

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/) y habilita la **Gmail API**.
2. Descarga las credenciales OAuth (tipo “Escritorio” o similar) y guárdalas como `credentials.json` en la raíz del proyecto.
3. La primera vez que uses un endpoint de Gmail, el cliente OAuth puede abrir el navegador y generar `token.json`.

Los adjuntos se guardan en `storage/gmail_attachments` (se crea automáticamente).

## Ejecutar el servidor

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Equivalente sin activar el venv:

```powershell
.\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Documentación de la API (Swagger)

| URL | Uso |
|-----|-----|
| http://127.0.0.1:8000/swagger | Swagger UI (interactivo) |
| http://127.0.0.1:8000/redoc | ReDoc |
| http://127.0.0.1:8000/openapi.json | Esquema OpenAPI |
| http://127.0.0.1:8000/health | Health check |
| http://127.0.0.1:8000/ | Redirige a `/swagger` |

Los endpoints de negocio están bajo el prefijo **`/api/v1`**:

- **Siniestros** — listado, detalle, scoring
- **Gmail** — registro de watch, escaneo manual
- **Webhooks** — push de Pub/Sub (Gmail)

## Estructura del proyecto

```
app/
  main.py              # Punto de entrada FastAPI
  api/v1/              # Routers y endpoints
  core/config.py       # Settings desde .env
  db/                  # Sesión SQLAlchemy
  models/              # Modelos ORM
  schemas/             # Pydantic
  integrations/        # Gmail, PDF, scoring
alembic/               # Migraciones
requirements.txt
.env.example
```

## Problemas frecuentes

**Error de conexión a la base de datos**

- Comprueba que `DATABASE_URL` en `.env` sea correcto (usuario, host, puerto, nombre de BD).
- Si usabas Docker antes, el puerto **5433** ya no aplica; en local suele ser **5432**.
- Si en la terminal tienes `DATABASE_URL` exportada, puede pisar el `.env`. En PowerShell: `Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue`.

**`password authentication failed`**

- Las credenciales de PostgreSQL no coinciden con las de `DATABASE_URL`.

**Swagger en 404**

- Asegúrate de usar `/swagger` (no `/docs`) y de tener el servidor en marcha con el código actual.

**Puerto 8000 ocupado**

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

## Desarrollo

- Recarga automática: `--reload` en uvicorn.
- Logs SQL: `SQLALCHEMY_ECHO=true` en `.env`.
- Python path: el proyecto asume ejecución desde la raíz del repo (donde está `app/`).
