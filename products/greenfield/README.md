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

## Verification

```bash
pnpm lint
pnpm test
pnpm build
```

The benchmark controller records the exact runtime, dependency lockfile, source commit, and verification outputs for every product snapshot.

