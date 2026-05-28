# fraude-back

Backend en **FastAPI** para gestionar **siniestros/reclamos** y la **ingesta/sincronización de correos de Gmail** (descarga de adjuntos y endpoints de webhook).

## Qué hay en este repo

- **API**: `FastAPI` en `app/main.py`
- **DB**: `SQLAlchemy` (2.x) + `Alembic` (migraciones)
- **Integraciones**: `app/integrations/gmail/` y parseo de PDFs en `app/integrations/siniestros/`
- **Storage local**: carpeta `storage/` (por defecto `storage/gmail_attachments`)

## Requisitos

- **Python**: 3.11+ (localmente puedes usar 3.12)
- **Docker**: no se usa en este proyecto.

## Configuración (variables de entorno)

El proyecto usa `pydantic-settings` y lee variables desde `.env` (si existe) y/o desde el entorno.

Variables más importantes (ver `app/core/config.py`):

- `DATABASE_URL`: URL SQLAlchemy de Postgres
- `APP_ENV`: `development` / `production` (default: `development`)
- `API_V1_STR`: prefijo API (default: `/api/v1`)
- Gmail:
  - `GMAIL_CLIENT_SECRET_FILE` (por defecto: `/app/credentials.json`)
  - `GMAIL_TOKEN_FILE` (por defecto: `/app/token.json`)
  - `GMAIL_WATCH_TOPIC` (si usas Pub/Sub watch)
  - `GMAIL_KEYWORDS`, `GMAIL_QUERY_HOURS_BACK`, `GMAIL_MAX_RESULTS`

> Nota: `.env` está en `.gitignore`, **no lo commitees**.

## Cómo ejecutar (Local)

1) Instalar dependencias:

```bash
python -m pip install -r requirements.txt
```

2) Exportar `DATABASE_URL` (ejemplo Neon):

```powershell
$env:DATABASE_URL='postgresql+psycopg2://neondb_owner:<PASSWORD>@<HOST>:5432/neondb?sslmode=require'
```

3) Correr migraciones:

```bash
alembic upgrade head
```

4) Levantar la API:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

La API quedará en `http://127.0.0.1:8000` y la documentación en:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`


## Migraciones (Alembic)

- Configuración: `alembic.ini`
- Entorno: `alembic/env.py` (toma `DATABASE_URL` desde `Settings().database_url`)
- Migrar:

```bash
alembic upgrade head
```

- Ver revisión actual:

```bash
alembic current
```

## Rutas principales

El router v1 está en `app/api/v1/router.py` y expone endpoints en:

- `${API_V1_STR}` (por defecto `/api/v1`)
  - `siniestros`
  - `gmail`
  - `webhooks`

Para ver la lista exacta de rutas, abre `http://localhost:8000/docs`.

