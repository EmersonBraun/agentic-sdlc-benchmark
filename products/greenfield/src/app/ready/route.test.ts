import { beforeEach, describe, expect, it, vi } from "vitest";

const { queryRaw, disconnect, createPrismaClient } = vi.hoisted(() => {
  const queryRaw = vi.fn();
  const disconnect = vi.fn(async () => undefined);
  const createPrismaClient = vi.fn(() => ({
    client: {
      $queryRaw: queryRaw,
    },
    disconnect,
  }));
  return { queryRaw, disconnect, createPrismaClient };
});

vi.mock("@/lib/db", () => ({
  createPrismaClient,
}));

describe("GET /ready", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    process.env.DATABASE_URL =
      "postgresql://app:app@localhost:5432/agentic_sdlc_greenfield";
  });

  it("responds 200 ready when the database is reachable", async () => {
    queryRaw.mockResolvedValueOnce([{ "?column?": 1 }]);
    const { GET } = await import("./route");

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({
      service: "greenfield-product",
      status: "ready",
      checks: { database: "ok" },
    });
    expect(disconnect).toHaveBeenCalledTimes(1);
  });

  it("responds 503 not_ready when the database is unavailable", async () => {
    queryRaw.mockRejectedValueOnce(
      new Error("password=super-secret connection failed at db.internal"),
    );
    const { GET } = await import("./route");

    const response = await GET();
    const body = await response.json();
    const serialized = JSON.stringify(body);

    expect(response.status).toBe(503);
    expect(body).toEqual({
      service: "greenfield-product",
      status: "not_ready",
      checks: { database: "unavailable" },
    });
    expect(serialized).not.toMatch(/super-secret|db\.internal|password=/i);
    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});
