# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 FastAPI backend for fraud/siniestro processing. The application entry point is `app/main.py`, with API routing under `app/api/v1/`. Endpoint modules live in `app/api/v1/endpoints/`, database models in `app/models/`, Pydantic schemas in `app/schemas/`, and database setup in `app/db/`. Domain integrations are grouped under `app/integrations/`, including Gmail ingestion and siniestro scoring/PDF parsing. Alembic configuration is in `alembic.ini`; migration scripts are in `alembic/versions/`.

## Build, Test, and Development Commands

- `python -m venv .venv` then `.venv\Scripts\Activate.ps1`: create and activate a local virtual environment on Windows.
- `pip install -r requirements.txt`: install FastAPI, SQLAlchemy, Alembic, Gmail, PDF/OCR, and OpenAI dependencies.
- `uvicorn app.main:app --reload`: run the API locally using `.env` settings.
- `docker compose up --build`: start the app and Postgres together; the API is exposed on `http://localhost:8000` and Postgres on host port `5433`.
- `alembic upgrade head`: apply database migrations.
- `alembic revision --autogenerate -m "describe change"`: create a new migration after model changes.

## Coding Style & Naming Conventions

Follow the existing style: 4-space indentation, type hints on public functions where practical, lowercase snake_case for modules/functions/variables, and PascalCase for SQLAlchemy/Pydantic classes. Keep API routers thin; place parsing, Gmail, scoring, and AI logic in `app/integrations/`. Prefer environment-backed settings through `app/core/config.py` instead of hard-coded paths or credentials.

## Testing Guidelines

No test suite is currently present. Add tests under `tests/` when introducing behavior, using `pytest` conventions such as `test_siniestros.py` and `test_<function_name>`. Favor focused tests around scoring, PDF parsing, settings, and endpoint behavior. If adding pytest, include it in `requirements.txt` or a dedicated dev requirements file and document the command, typically `pytest`.

## Commit & Pull Request Guidelines

Recent history uses short, descriptive commits, including Spanish summaries such as `Score implementado, endpoint de siniestros y de score`. Keep commits concise and behavior-focused. Pull requests should describe the change, list migration or configuration impacts, mention test results, and link related issues when available. For API changes, include affected routes and example request/response details.

## Security & Configuration Tips

Do not commit real `.env`, `credentials.json`, `token.json`, or downloaded Gmail attachments. Use `.env` for local configuration and keep secrets out of source control. When changing Gmail, OpenAI, or database settings, update `app/core/config.py`, Docker Compose environment values, and deployment secrets consistently.
