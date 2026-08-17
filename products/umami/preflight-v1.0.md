# Umami Preflight v1.0

## Decision

Accept Umami `v3.3.0` as the brownfield benchmark snapshot:

`ba2aa48546534c55e9b8174667b4f266fe9d9ea2`

## Checks

- License: MIT confirmed.
- Source snapshot: immutable release tag and commit recorded.
- Dependency lockfile: `pnpm install --frozen-lockfile` passed.
- Controlled Docker build: passed with Node 22 Alpine, pnpm 11.21.0, and Prisma 7.9.1.
- Controlled test suite: 86 suites and 713 tests passed.
- Database-dependent build inputs: Prisma generation completed with a deterministic dummy PostgreSQL URL.
- Production build: passed, including tracker, recorder, geo, and Next.js application build.

## Rejected snapshot

Umami `v3.0.0` was rejected. Its upstream test run had five failures because the test file imported `detect.ts` while calling `getIpAddress`, which is exported from `ip.ts`. The failure is retained as preflight evidence and was not silently repaired.

## Environment note

The host machine runs Node 25, which produced localStorage-related test failures in the v3.3.0 suite. The benchmark does not use that host runtime for product execution. It uses the pinned Docker environment. The host machine remains recorded as infrastructure context.

The upstream GitHub Actions workflow uses a different pnpm setup. For benchmark comparability, CI and local execution use the pinned Docker environment; the upstream workflow remains provenance evidence only.

## Reproduction

The preflight can be repeated from the upstream tag with:

```bash
git clone --branch v3.3.0 https://github.com/umami-software/umami.git
cd umami
docker build --tag umami-preflight:v3.3.0 .
```

The complete image and builder identifiers, lockfile hashes, and source commit are recorded in `snapshot-v1.0.json`.
