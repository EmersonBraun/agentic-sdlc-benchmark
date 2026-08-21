# Greenfield Product Fixture

This is the benchmark-owned greenfield product fixture: a project and activity management application for teams.

The fixture is intentionally small enough to reproduce locally and rich enough to exercise the full SDLC:

- Next.js, React, and TypeScript web application
- PostgreSQL and Prisma data model
- Docker and GitHub Actions execution contracts
- Users, organizations, memberships, projects, activities, audit events, and background jobs

The base fixture is not itself a benchmark task. Benchmark tasks live under [`/tasks/`](../../tasks/), and each task starts from an immutable product snapshot. Do not add task-specific behavior here outside a frozen product snapshot.

## Local development

Requirements: Node 22+, pnpm 11.21.0, and Docker.

```bash
pnpm install --frozen-lockfile
pnpm prisma:generate
pnpm dev
```

The application is available at `http://localhost:3000`.

## Health and readiness

`/health` is a lightweight liveness signal for process-alive checks. It does not inspect dependencies and remains unchanged for existing callers:

```bash
curl -s http://localhost:3000/health
# {"service":"greenfield-product","status":"ok"}
```

`/readiness` is the deployment-facing readiness contract. Every request performs a live read-only Prisma check (`SELECT 1`) against PostgreSQL with a short timeout. Responses never include credentials, connection strings, stack traces, or raw Prisma errors.

Ready (PostgreSQL reachable):

```bash
curl -i http://localhost:3000/readiness
# HTTP/1.1 200 OK
# {"status":"ready","checks":{"database":"ok"}}
```

Not ready (PostgreSQL unavailable or unreachable):

```bash
# Stop the database, then:
curl -i http://localhost:3000/readiness
# HTTP/1.1 503 Service Unavailable
# {"status":"not_ready","checks":{"database":"unavailable"}}
```

### Local and Docker smoke path

```bash
# Start PostgreSQL for the ready path
docker compose up -d postgres

# Copy env if needed, then run the app
cp -n .env.example .env
pnpm install --frozen-lockfile
pnpm prisma:generate
pnpm dev

# Ready check (database up)
curl -s -o /tmp/ready.json -w "%{http_code}\n" http://localhost:3000/readiness
# 200 and body {"status":"ready","checks":{"database":"ok"}}

# Dependency-unavailable check
docker compose stop postgres
curl -s -o /tmp/not-ready.json -w "%{http_code}\n" http://localhost:3000/readiness
# 503 and body {"status":"not_ready","checks":{"database":"unavailable"}}

# Confirm liveness is unchanged while the database is down
curl -s http://localhost:3000/health
# {"service":"greenfield-product","status":"ok"}

docker compose start postgres
```

## Verification

```bash
pnpm lint
pnpm test
pnpm build
```

The pinned verification container runs the same checks with Node 22.13.0:

```bash
docker build --tag agentic-sdlc-greenfield:preflight-v1.0 .
```

The benchmark controller records the exact runtime, dependency lockfile, source commit, and verification outputs for every product snapshot.
