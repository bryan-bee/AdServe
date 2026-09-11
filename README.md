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
│   ├── api/routes/   # HTTP endpoints
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic request/response schemas
│   ├── services/     # Auction, targeting, business logic
│   ├── db/           # Session, engine, migrations glue
│   └── core/         # Config, logging, shared plumbing
├── tests/
├── scripts/          # Seeding, simulated traffic
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
```

The app itself lands in step 2.

## Build order

1. **Repo scaffold (ADS-001)** — structure above, plus `.gitignore`, `README.md`, `requirements.txt`, `.env.example`. ✅
2. **Minimal FastAPI app** — `GET /health`, confirming the skeleton runs.
3. **Postgres + core domain** — Postgres via Docker Compose; campaigns, advertisers, audience-targeting models/endpoints.
4. **Fake data generation** — scripts to seed fake advertisers, campaigns, content, and users.
5. **Ad auction/ranking v1** — scored/rule-based auction picking a winning ad for a simulated request.
6. **Simulated traffic + Locust** — fire impressions/clicks/conversions at the auction endpoint; ramp concurrent users and watch it hold.
7. **Redis** — once there's a real hot-path lookup to cache (campaign/targeting data).
8. **Kafka** — once there's a real async need (decoupling impression/click events from the request path for analytics/billing).
9. **React dashboard + Prometheus/Grafana** — live metrics: auction latency, CTR, req/sec.
10. **(Optional, later) AWS via Terraform/CDK** — RDS/ElastiCache/MSK and deploy.
