export const READINESS_PROBE_TIMEOUT_MS = 2_000;

export type DatabaseCheck = "ok" | "unavailable";

export type ReadinessBody = {
  service: "greenfield-product";
  status: "ready" | "not_ready";
  checks: {
    database: DatabaseCheck;
  };
};

export type ReadinessResult = {
  httpStatus: 200 | 503;
  body: ReadinessBody;
};

type Queryable = {
  $queryRaw: (
    strings: TemplateStringsArray,
    ...values: unknown[]
  ) => Promise<unknown>;
};

/** Read-only DB reachability probe; failures and timeouts map to unavailable. */
export async function probeDatabase(
  client: Queryable,
  timeoutMs = READINESS_PROBE_TIMEOUT_MS,
): Promise<DatabaseCheck> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      client.$queryRaw`SELECT 1`,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("database_probe_timeout")),
          timeoutMs,
        );
      }),
    ]);
    return "ok";
  } catch {
    return "unavailable";
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

export function toReadinessResult(database: DatabaseCheck): ReadinessResult {
  if (database === "ok") {
    return {
      httpStatus: 200,
      body: {
        service: "greenfield-product",
        status: "ready",
        checks: { database: "ok" },
      },
    };
  }

  return {
    httpStatus: 503,
    body: {
      service: "greenfield-product",
      status: "not_ready",
      checks: { database: "unavailable" },
    },
  };
}

/** Evaluate readiness; missing DATABASE_URL or probe failure => not_ready. */
export async function evaluateReadiness(options: {
  connectionString: string | undefined;
  createClient: (connectionString: string) => {
    client: Queryable;
    disconnect: () => Promise<void>;
  };
  timeoutMs?: number;
}): Promise<ReadinessResult> {
  const { connectionString, createClient, timeoutMs } = options;

  if (!connectionString) {
    return toReadinessResult("unavailable");
  }

  const handle = createClient(connectionString);
  try {
    const database = await probeDatabase(handle.client, timeoutMs);
    return toReadinessResult(database);
  } finally {
    await handle.disconnect().catch(() => undefined);
  }
}
