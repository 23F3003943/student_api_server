# Student API Server

This repository contains a small FastAPI application that accepts student task submissions and processes them asynchronously with Celery. The worker creates a simple project repository, pushes it to GitHub (if configured), enables GitHub Pages, and notifies an evaluator endpoint.

This README explains how to run the project locally and with Docker Compose.

## What this project does
- Exposes POST `/api-endpoint` to accept a task submission (email, secret, task, round, nonce)
- Stores a `Task` record in a database and returns an immediate acknowledgement
- Dispatches a Celery background job to process the task (create repo, push commit, enable pages, notify evaluator)

## Requirements
- Docker & Docker Compose (recommended)
- Or: Python 3.9, Poetry (or pip) and local Redis/Postgres for full functionality

## Security note
Do NOT commit secrets to the repository. The project uses a `.env` file for configuration — add secrets there and keep the file out of version control. A sample `.env` should include at least:

```
EXPECTED_SECRET="YOYO"
GITHUB_TOKEN="ghp_..."
DATABASE_URL="postgresql://admin:password123@db:5432/sas_db"
REDIS_URL="redis://redis:6379/0"
```

If you have committed secrets earlier, rotate them immediately.

## Run with Docker Compose (recommended)
This starts the API, a Celery worker, Redis and Postgres.

1. From the project root, create a `.env` (copy values locally). Make sure `.env` contains `EXPECTED_SECRET` and any tokens you need.
2. Start services:

```powershell
docker-compose up --build
```

3. Open the API docs: http://localhost:8000/docs

4. Submit a POST to `/api-endpoint` with JSON body. Example payload:

```json
{
	"email": "you@example.com",
	"secret": "YOYO",
	"task": "demo",
	"round": 1,
	"nonce": "unique-nonce-001"
}
```

Notes:
- If you want to use GitHub integration, add a `GITHUB_TOKEN` with repo/pages permissions to `.env`.
- Use a unique `nonce` per submission. The API is idempotent: resubmitting the same nonce returns the stored task status.

## Run locally without Docker
1. Install dependencies with Poetry:

```powershell
poetry install
```

2. Create a `.env` with the configuration. For a quick test without Postgres you can use sqlite by setting `DATABASE_URL="sqlite:///./test.db"` and run a local Redis instance if you want Celery to process jobs.

3. Start the web server:

```powershell
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Start the Celery worker in a separate terminal (if you want background jobs to run):

```powershell
poetry run celery -A workers.tasks.celery_app worker --loglevel=info
```

## Database
- The app uses SQLAlchemy. By default the app will create tables at startup using `Base.metadata.create_all(bind=engine)`.

## Development tips
- Add `.env` to your local `.gitignore` (this repo's `.gitignore` will be updated).
- If you add or change models, migrations can be added with Alembic (not included here).

## Troubleshooting
- 403 Forbidden: your `secret` value does not match `EXPECTED_SECRET`.
- 400/409 on nonce: The API will return the existing task for duplicate nonces (idempotent behavior).
- Celery tasks fail: check worker logs and ensure `REDIS_URL` is reachable and `GITHUB_TOKEN` is valid if GitHub operations are attempted.

## License
MIT
