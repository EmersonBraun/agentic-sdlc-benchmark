import { PrismaPg } from "@prisma/adapter-pg";

import { PrismaClient } from "@/generated/prisma/client";

/** Fail-fast budget for establishing a readiness DB connection. */
export const DB_CONNECTION_TIMEOUT_MS = 2_000;

export type PrismaHandle = {
  client: PrismaClient;
  disconnect: () => Promise<void>;
};

/** Short-lived Prisma client using @prisma/adapter-pg with a bounded connect timeout. */
export function createPrismaClient(
  connectionString: string,
  connectionTimeoutMillis = DB_CONNECTION_TIMEOUT_MS,
): PrismaHandle {
  const adapter = new PrismaPg({
    connectionString,
    connectionTimeoutMillis,
    max: 1,
  });
  const client = new PrismaClient({ adapter });

  return {
    client,
    disconnect: async () => {
      await client.$disconnect().catch(() => undefined);
    },
  };
}
