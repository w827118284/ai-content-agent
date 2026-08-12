# Docker Compose Deployment

This deployment runs PostgreSQL 18, a one-shot Alembic migration, FastAPI, and
the React production build behind Nginx. The only host entry point is
`http://localhost:8080`; PostgreSQL and FastAPI stay on the Compose network.

## Prerequisites

- Docker Engine with Docker Compose
- On this Windows workstation, run Docker commands through `Ubuntu-24.04` WSL

## Configure

Create the local Docker environment file from the committed example:

```powershell
Copy-Item .env.docker.example .env.docker
```

Replace the PostgreSQL and JWT placeholders in `.env.docker`. The JWT secret
must contain at least 32 UTF-8 bytes. Keep `USE_MOCK_LLM=true` and
`USE_MOCK_IMAGE=true` for deployment smoke tests. If the PostgreSQL password
contains URL-reserved characters, URL-encode it in `DATABASE_URL`. Never copy
`backend/.env` into `.env.docker`.

LangSmith tracing is optional and disabled by default. A deployment without a
LangSmith key must keep working normally. The committed example also defaults
`LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` so workflow
topics, articles, and review feedback are not uploaded as raw trace payloads.
Only set `LANGSMITH_API_KEY` in the ignored `.env.docker` file when tracing is
intentionally enabled.

## Start

Run from the repository root:

```bash
docker compose --env-file .env.docker config -q
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d
docker compose --env-file .env.docker ps -a
```

Open `http://localhost:8080`. Nginx serves the SPA and proxies `/api/` plus the
exact `/health` route to FastAPI.

The startup order is database health, Alembic completion, backend health, then
frontend. Alembic manages only business tables. LangGraph's
`AsyncPostgresSaver.setup()` continues to manage checkpoint tables when the
backend starts.

PostgreSQL 18 stores data under `/var/lib/postgresql/18/docker`; Compose mounts
the named volume at `/var/lib/postgresql`, as required by the PostgreSQL 18
official image.

## Inspect

```bash
docker compose --env-file .env.docker logs backend
docker compose --env-file .env.docker logs migrate
docker compose --env-file .env.docker logs frontend
```

## Stop

Preserve the PostgreSQL volume:

```bash
docker compose --env-file .env.docker down
```

To permanently remove local Docker data:

```bash
docker compose --env-file .env.docker down -v
```

`down -v` deletes the PostgreSQL volume and all users, history, and workflow
checkpoints stored in it.
