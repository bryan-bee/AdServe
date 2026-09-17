# AdServe

A mini real-time ad-serving / ad-auction platform.

There's no real traffic, so the project generates its own: fake advertisers, campaigns,
users, and simulated impressions/clicks/conversions, all flowing through a real
auction/ranking engine you can load-test.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | Python + FastAPI |
| Database | PostgreSQL (source of truth) |
| Cache | Redis (auction candidate cache, rate limiting, idempotency keys) |
| Async events | Kafka (clicks/conversions → standalone consumer → Postgres) |
| Metrics | Prometheus + Grafana |
| Dashboard | React + Vite |
| Load testing | Locust |
| Containers | Docker + Docker Compose |

Cloud is deferred. The project is built local-first but portable: standard
Postgres/Redis/Kafka, env-var config, stateless containers — so moving to
RDS/ElastiCache/MSK later is a config change, not a rewrite.

## What it does

- **`POST /auction`** runs a three-stage auction — filter eligible campaigns → score them →
  pick a winner by weighted random selection — then charges the winner and logs an impression.
- **Clicks and conversions are event-driven**: the endpoints publish to Kafka and return
  immediately; a separate consumer process writes them to Postgres.
- **Interest weights are learned from clicks.** The consumer nudges a user's interest weights
  based on what they click, and the auction's scoring reads those weights back — so clicking
  changes which ads that user sees next.
- **The API is hardened**: API-key auth on advertiser writes, per-IP rate limiting, optional
  idempotency keys, and a timing-based click-fraud heuristic.

---

## Running it after cloning

### 1. Prerequisites

- **Python 3.11+**
- **Docker Desktop** (running)
- **Node.js 18+** — only needed for the React dashboard

### 2. Python environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment file

```bash
# Windows:
copy .env.example .env
# macOS/Linux:
cp .env.example .env
```

The defaults work as-is for local development.

### 4. Start the infrastructure

```bash
docker compose up -d
```

This starts five containers: **Postgres** (5432), **Redis** (6379), **Kafka** (9092),
**Prometheus** (9090), and **Grafana** (3000).

### 5. Create the Kafka topic

One-time setup — the app publishes here and the consumer reads from it:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic adserve.events --partitions 3 --replication-factor 1
```

### 6. Apply migrations and seed data

```bash
alembic upgrade head
python -m scripts.seed
```

`scripts/seed.py` generates advertisers, campaigns with targeting, interests, and a large
batch of users. It's idempotent — it truncates first, so re-running always gives a clean,
reproducible dataset.

### 7. Run the API

```bash
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/health` — should return `{"status": "ok"}`.
Interactive API docs are at `http://127.0.0.1:8000/docs`.

### 8. Run the event consumer

Clicks and conversions only reach Postgres once this is running. In a **separate terminal**:

```bash
python -m scripts.consume_events
```

Leave it running. Without it, click/conversion endpoints still succeed (the events queue
durably in Kafka), they just won't appear in the database until a consumer drains them.

### 9. Run the dashboard

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. It proxies `/api/*` to the backend, so both need to be running.

### 10. Grafana

Open `http://localhost:3000` and log in with **admin / admin**. The "AdServe" folder contains
a pre-provisioned **Service Overview** dashboard (request rates, latency percentiles, auction
fill rate, fraud and idempotency counters). The datasource and dashboard are provisioned from
files in `grafana/`, so there's nothing to set up by hand.

---

## Running with multiple workers

`--reload` runs a single process, which is fine for development. To run it the way it's
actually been benchmarked:

```bash
# Windows (Git Bash)
export PROMETHEUS_MULTIPROC_DIR=/tmp/adserve_metrics
rm -rf "$PROMETHEUS_MULTIPROC_DIR" && mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

`PROMETHEUS_MULTIPROC_DIR` is **required** with multiple workers. Each worker is a separate
process with its own in-memory counters, so without it `/metrics` returns whichever single
worker happened to answer — inconsistent numbers that break Prometheus's assumptions. The
directory must be emptied before each start, or metrics from previous runs' dead workers get
merged in.

Bind to `0.0.0.0`, not `127.0.0.1`, or Prometheus (running in a container) can't scrape the
app running on the host.

---

## Testing

```bash
python -m pytest tests/ -v
```

Unit tests need no setup. Integration tests run against a separate `adserve_test` database
(same Postgres container, never touches dev data). One-time setup:

```bash
docker compose exec db psql -U adserve -d adserve -c "CREATE DATABASE adserve_test OWNER adserve;"
DATABASE_URL=postgresql+psycopg://adserve:adserve@localhost:5432/adserve_test alembic upgrade head
python -m scripts.seed_test
```

Each integration test runs inside a transaction that's rolled back afterward (see
`tests/conftest.py`), so the test database always stays in the same seeded state.

**Note:** when adding a migration, apply it to both databases — `alembic upgrade head` only
targets the dev database.

---

## Load testing

```bash
locust -f locustfile_fast.py --headless -u 100 -r 50 -t 25s --host http://127.0.0.1:8000
```

`locustfile_fast.py` has no think time, so the user count directly controls concurrent load.
`locustfile.py` is the realistic variant with 1–3s pauses between requests.

⚠️ **Rate limiting will interfere.** The limiter allows 100 requests per 10s *per IP*, and all
Locust traffic comes from one machine — so any meaningful load test hits `429`s almost
immediately. Raise `AUCTION_RATE_LIMIT` in `app/core/rate_limit.py` before benchmarking.

For accurate numbers on Windows, run the app *inside* a container on the Docker network —
Docker Desktop's port-forwarder adds a fixed ~44ms to database round trips from the host,
which will dominate any measurement taken from outside.

---

## Layout

```
adserve/
├── app/
│   ├── api/routes/   # HTTP endpoints (auction, advertisers, campaigns, clicks, analytics)
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic request/response schemas
│   ├── services/     # Auction logic (filter -> score -> pick winner), Kafka producer
│   ├── db/           # Session, engine, Redis client
│   └── core/         # Config, metrics, security, rate limiting, idempotency
├── alembic/          # Migrations
├── frontend/         # React + Vite dashboard
├── grafana/          # Provisioned datasource + dashboards
├── scripts/          # Seeding, simulated traffic, the Kafka consumer
├── tests/
├── docker-compose.yaml
├── prometheus.yml
├── locustfile.py / locustfile_fast.py
└── .env.example
```

## API overview

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `POST /auction` | none | Rate limited. `204` = no eligible campaign ("no fill") |
| `POST /advertisers` | none | Sign-up; returns an API key **once** |
| `POST /campaigns` | `X-API-Key` | Owner comes from the key, not the request body |
| `POST /campaigns/{id}/targeting` | `X-API-Key` | Must own the campaign |
| `POST /impressions/{id}/clicks` | none | Publishes to Kafka. Accepts `Idempotency-Key` |
| `POST /clicks/{id}/conversions` | none | Publishes to Kafka. Accepts `Idempotency-Key` |
| `GET /analytics/*` | none | Aggregates for the dashboard |
| `GET /metrics` | none | Prometheus exposition |
