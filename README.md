# AdServe

A mini real-time ad-serving / ad-auction platform simulator.

There's no real traffic, so the project generates its own: fake advertisers, campaigns,
users, and simulated impressions/clicks/conversions, all flowing through a real
auction/ranking engine you can load-test.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | Python + FastAPI |
| Database | PostgreSQL (source of truth) |
| Cache | Redis |
| Async events | Kafka |
| Load testing | Locust |
| Containers | Docker + Docker Compose |
| Later | React dashboard, Prometheus + Grafana, ranking/CTR with scikit-learn |

Cloud is deferred. The project is built local-first but portable: standard
Postgres/Redis/Kafka, env-var config, stateless containers — so moving to
RDS/ElastiCache/MSK later is a config change, not a rewrite.

## Layout

```
adserve/
├── app/
│   ├── api/routes/   # HTTP endpoints (advertisers, campaigns, auction, health)
│   ├── models/       # SQLAlchemy models (Advertiser, Campaign, AudienceTargeting, User, Interest)
│   ├── schemas/      # Pydantic request/response schemas
│   ├── services/     # Auction logic (filter -> score -> pick winner)
│   ├── db/           # Session, engine, base
│   └── core/         # Config, logging, shared plumbing
├── alembic/          # Migrations (env.py, versions/)
├── alembic.ini
├── tests/            # Unit tests + integration tests (against a separate test DB)
├── scripts/          # Seeding (prod-scale + a small deterministic test-DB seed), simulated traffic
├── docker-compose.yaml  # Postgres (+ Redis/Kafka later)
├── .gitignore
├── README.md
├── requirements.txt
└── .env.example
```

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
docker compose up -d          # starts Postgres
alembic upgrade head          # applies migrations
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/health` — should return `{"status": "ok"}`.

## Testing

Unit tests need no setup — they run against plain in-memory objects, no database required:

```bash
python -m pytest tests/test_auction.py -v
```

Integration tests run against a separate `adserve_test` database (same Postgres container,
never touches real dev data), so tests can freely read/write without risk. One-time setup:

```bash
docker compose exec db psql -U adserve -d adserve -c "CREATE DATABASE adserve_test OWNER adserve;"
DATABASE_URL=postgresql+psycopg://adserve:adserve@localhost:5432/adserve_test alembic upgrade head
python -m scripts.seed_test
```

Then run the full suite the same way:

```bash
python -m pytest tests/ -v
```

Each integration test runs inside a transaction that's rolled back afterward (see
`tests/conftest.py`), so the test database always stays in the same seeded state.

## Build order

A living backlog lives in `ROADMAP.md` (gitignored, local planning doc — not checked into the
repo) with finer-grained ticket breakdowns. This is the high-level summary:

1. **Repo scaffold (ADS-001)** — structure above, plus `.gitignore`, `README.md`, `requirements.txt`, `.env.example`. ✅
2. **Minimal FastAPI app (ADS-002)** — `GET /health`, confirming the skeleton runs. ✅
3. **Postgres + core domain (ADS-003)** — Postgres via Docker Compose, Alembic migrations;
   `Advertiser`, `Campaign`, `AudienceTargeting` models and endpoints. ✅
4. **Fake data & the User entity** — a real `User` model (identity, demographics, device,
   interests), plus `Faker`-based seed scripts generating realistic advertisers, campaigns,
   and a large batch of users (~2M) via batched bulk insert. ✅
5. **Ad auction/ranking v1** — rule-based auction, structured as separable filter → score →
   pick-winner stages (kept separable so a trained model can later replace the scoring stage
   without a rewrite), exposed via `POST /auction`. ✅
6. **Simulated traffic + Locust** — event logging (impressions/clicks/conversions with full
   decision-time context, captured now because it can't be reconstructed later), traffic
   simulation scripts, and Locust load tests against the auction endpoint.
7. **Horizontal scaling** — once Locust reveals a real bottleneck on a single `uvicorn`
   process, run multiple app instances (Docker Compose `--scale` or Nginx) and re-test.
8. **Redis** — caching whatever hot-path lookup (likely campaign/targeting) proves worth it
   under measured load, plus rate limiting on the auction endpoint.
9. **Kafka** — publish impression/click events asynchronously instead of inline in the
   request path; a consumer reads them into Postgres/analytics storage.
10. **User preference learning** — heuristic click/no-click scoring first (a Kafka consumer
    nudging interest scores), later swapped for a trained `scikit-learn` model once enough
    real interaction history exists.
11. **React dashboard + Prometheus/Grafana** — `prometheus-fastapi-instrumentator` metrics
    (auction latency, request counts, CTR), Grafana dashboards, and a small React frontend
    over new read-oriented analytics endpoints.
12. **(Optional) AWS via Terraform/CDK** — RDS/ElastiCache/MSK and deploy.
