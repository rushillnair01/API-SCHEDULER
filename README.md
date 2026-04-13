# API Cron Job Tool

A Docker-based scheduler that fires HTTP requests on a cron-like interval, tracks every run in PostgreSQL, exposes Prometheus metrics, and recovers cleanly from crashes.

## Architecture

```text
┌─────────────┐     HTTP      ┌─────────────┐     ORM      ┌──────────────┐
│  Dashboard  │ ────────────► │   FastAPI   │ ───────────► │  PostgreSQL  │
│ (dashboard) │               │    (api)    │              │     (db)     │
└─────────────┘               └─────────────┘              └──────────────┘
                                                                  ▲
┌─────────────┐   .delay()    ┌─────────────┐     ORM             │
│  Scheduler  │ ────────────► │    Redis    │ ──────────► ┌──────────────┐
│ (scheduler) │               │   (broker)  │             │    Celery    │
└─────────────┘               └─────────────┘             │   (worker)   │
                                                          └──────────────┘
```

| Service     | Technology   | Role                                      |
| :---------- | :----------- | :---------------------------------------- |
| **db**      | PostgreSQL   | The Source of Truth (targets, schedules, runs) |
| **redis**   | Redis        | The Task Queue & Broker                   |
| **api**     | FastAPI      | The Control Plane (REST API + Metrics)    |
| **scheduler**| celery beat  | Polling loop that dispatches due jobs     |
| **worker**  | Celery       | The Execution Plane (makes HTTP requests) |
| **dashboard**| Streamlit    | The UI for managing targets and schedules |

---

## Step 1 — Project Configuration

### `docker-compose.yml`

> **Note:** This configuration uses Docker volumes for data persistence and health checks to ensure proper startup sequencing.

```yaml
version: "3.9"

services:
  # 1. Database - The Source of Truth
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: scheduler_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d scheduler_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  # 2. Redis - The Task Queue & Broker
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # 3. FastAPI - The Control Plane (API)
  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  # 4. Celery Worker - The Execution Plane
  worker:
    build: .
    command: celery -A app.tasks.celery_app worker --loglevel=info
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/scheduler_db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  # 5. Scheduler - The Heart (Polling Loop)
  scheduler:
    build: .
    command: python app/scheduler.py
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - db
      - redis

  # 6. Streamlit Dashboard - The UI
  dashboard:
    build: .
    command: streamlit run app/frontend.py --server.port 8501 --server.address 0.0.0.0
    volumes:
      - .:/app
    ports:
      - "8501:8501"
    environment:
      - API_URL=http://api:8000
    depends_on:
      - api

# --- PERSISTENCE DEFINITION ---
volumes:
  postgres_data:
```

---

## Step 2 — Installation & Setup

### Build the Environment
```bash
docker compose build
```

### Initialize Database Tables (Alembic)
First, start the DB:
```bash
docker compose up -d db redis
```

Run the migration:
```bash
docker compose run --rm api alembic upgrade head
```

### Launch API CRON MAIN APP
```bash
docker compose up -d
```

---

## Step 3 — Access & Monitoring

| Interface   | URL                           |
| :---------- | :---------------------------- |
| Dashboard   | http://localhost:8501         |
| API Docs    | http://localhost:8000/docs    |
| Prometheus  | http://localhost:8000/metrics |

---

## Crash Recovery Protocol

**API CRON JOB** is designed to handle server disruptions gracefully.

*   **Ghost Tasks:** On startup, the scheduler identifies runs stuck in a `RUNNING` state (from a previous crash) and marks them as `INTERRUPTED`.
*   **Throttled Catch-up:** If the server was offline, the scheduler identifies missed cycles and dispatches them in a throttled burst (100ms delay) to avoid 429 Rate Limit errors from targets.
*   **Data Persistence:** All configurations and run history are stored in the `postgres_data` Docker volume and survive `docker compose down`.

---

## Management Commands

```bash
# View real-time logs for the recovery engine
docker compose logs -f scheduler

# Perform a "Nuclear Reset" (Wipe all data and start fresh)
docker compose down -v
docker compose up -d --build
docker compose run --rm api alembic upgrade head

# Inspect Database status via CLI
docker compose exec db psql -U user scheduler_db
```
