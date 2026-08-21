import { getPrismaClient } from "@/lib/prisma";

/** Short timeout budget suitable for deployment readiness probes. */
export const READINESS_TIMEOUT_MS = 2_000;

export type DatabaseCheckResult = "ok" | "unavailable";
export type ReadinessStatus = "ready" | "not_ready";

export type ReadinessResponseBody = {
  status: ReadinessStatus;
  checks: {
    database: DatabaseCheckResult;
  };
};

export type DatabaseProbe = () => Promise<unknown>;

/**
 * Live read-only PostgreSQL reachability check via Prisma.
 * Failures are normalized so callers never see connection strings,
 * credentials, stack traces, or raw Prisma diagnostics.
 */
export async function probeDatabase(
  probe: DatabaseProbe = defaultDatabaseProbe,
  timeoutMs: number = READINESS_TIMEOUT_MS,
): Promise<DatabaseCheckResult> {
  try {
    await withTimeout(probe(), timeoutMs);
    return "ok";
  } catch {
    return "unavailable";
  }
}

export function buildReadinessBody(
  database: DatabaseCheckResult,
): ReadinessResponseBody {
  if (database === "ok") {
    return { status: "ready", checks: { database: "ok" } };
  }
  return { status: "not_ready", checks: { database: "unavailable" } };
}

export function readinessHttpStatus(body: ReadinessResponseBody): 200 | 503 {
  return body.status === "ready" ? 200 : 503;
}

export async function evaluateReadiness(
  probe: DatabaseProbe = defaultDatabaseProbe,
  timeoutMs: number = READINESS_TIMEOUT_MS,
): Promise<{ status: 200 | 503; body: ReadinessResponseBody }> {
  const database = await probeDatabase(probe, timeoutMs);
  const body = buildReadinessBody(database);
  return { status: readinessHttpStatus(body), body };
}

async function defaultDatabaseProbe(): Promise<unknown> {
  const prisma = getPrismaClient();
  return prisma.$queryRaw`SELECT 1`;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error("readiness probe timed out"));
    }, timeoutMs);

    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
