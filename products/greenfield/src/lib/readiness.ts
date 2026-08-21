import { createPrismaClient } from "@/lib/prisma";

/** Bounded wait for deployment-style readiness probes. */
export const DATABASE_PROBE_TIMEOUT_MS = 2_000;

export type DatabaseCheckStatus = "ok" | "unavailable";

export type ReadinessPayload = {
  status: "ready" | "not_ready";
  checks: {
    database: DatabaseCheckStatus;
  };
};

export type DatabaseProbe = () => Promise<void>;

/**
 * Minimal Prisma-mediated PostgreSQL reachability probe.
 * Failures are intentionally swallowed by callers so responses never leak
 * credentials, connection strings, or driver/stack details.
 */
export async function probeDatabaseWithPrisma(): Promise<void> {
  const prisma = createPrismaClient();
  try {
    await prisma.$queryRaw`SELECT 1`;
  } finally {
    await prisma.$disconnect();
  }
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error("database probe timed out"));
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

export async function evaluateReadiness(
  probeDatabase: DatabaseProbe = probeDatabaseWithPrisma,
  timeoutMs: number = DATABASE_PROBE_TIMEOUT_MS,
): Promise<ReadinessPayload> {
  try {
    await withTimeout(probeDatabase(), timeoutMs);
    return {
      status: "ready",
      checks: { database: "ok" },
    };
  } catch {
    return {
      status: "not_ready",
      checks: { database: "unavailable" },
    };
  }
}

export function readinessHttpStatus(payload: ReadinessPayload): 200 | 503 {
  return payload.status === "ready" ? 200 : 503;
}
