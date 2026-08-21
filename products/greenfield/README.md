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

`/health` is a liveness signal only. It does not check dependencies:

```bash
curl -sS http://localhost:3000/health
# {"service":"greenfield-product","status":"ok"}
```

`/readyz` is the deployment readiness probe. It performs a read-only Prisma/`pg` reachability check against PostgreSQL (`SELECT 1`) with a fail-fast timeout. Responses never include credentials, connection strings, SQL text, stack traces, or other secrets—only redacted diagnostic state via `checks.database`.

### Ready response

- HTTP `200`
- Body: `{"service":"greenfield-product","status":"ready","checks":{"database":"ok"}}`

### Not ready response

- HTTP `503`
- Body: `{"service":"greenfield-product","status":"not_ready","checks":{"database":"unavailable"}}`

### Healthy app + database

Start Postgres, generate the client, and run the app:

```bash
docker compose up -d postgres
cp -n .env.example .env
pnpm install --frozen-lockfile
pnpm prisma:generate
pnpm dev
```

Then:

```bash
curl -i -sS http://localhost:3000/readyz
# HTTP/1.1 200
# {"service":"greenfield-product","status":"ready","checks":{"database":"ok"}}
```

### Database unavailable

With the app still running, stop Postgres (or point `DATABASE_URL` at a closed port) and call readiness again:

```bash
docker compose stop postgres
curl -i -sS http://localhost:3000/readyz
# HTTP/1.1 503
# {"service":"greenfield-product","status":"not_ready","checks":{"database":"unavailable"}}
```

Restore the dependency with `docker compose start postgres` when finished.

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
