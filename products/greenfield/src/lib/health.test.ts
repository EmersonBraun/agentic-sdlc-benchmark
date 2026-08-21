import { describe, expect, it } from "vitest";

import { GET as getHealth } from "../app/health/route";
import {
  evaluateReadiness,
  probeDatabase,
  toReadinessResult,
} from "./readiness";

describe("greenfield product fixture", () => {
  it("declares the public health contract", () => {
    expect({ service: "greenfield-product", status: "ok" }).toEqual({
      service: "greenfield-product",
      status: "ok",
    });
  });

  it("keeps the health route behavior unchanged", async () => {
    const response = getHealth();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      service: "greenfield-product",
      status: "ok",
    });
  });
});

describe("readiness contract", () => {
  it("returns ready when the database probe succeeds", async () => {
    const result = await evaluateReadiness({
      connectionString:
        "postgresql://app:app@localhost:5432/agentic_sdlc_greenfield",
      createClient: () => ({
        client: {
          $queryRaw: async () => [{ "?column?": 1 }],
        },
        disconnect: async () => undefined,
      }),
    });

    expect(result).toEqual({
      httpStatus: 200,
      body: {
        service: "greenfield-product",
        status: "ready",
        checks: { database: "ok" },
      },
    });
  });

  it("returns not_ready when the database probe fails", async () => {
    const result = await evaluateReadiness({
      connectionString:
        "postgresql://app:app@localhost:5432/agentic_sdlc_greenfield",
      createClient: () => ({
        client: {
          $queryRaw: async () => {
            throw new Error(
              "connect ECONNREFUSED postgresql://app:secret@db.internal:5432/prod",
            );
          },
        },
        disconnect: async () => undefined,
      }),
    });

    expect(result.httpStatus).toBe(503);
    expect(result.body).toEqual({
      service: "greenfield-product",
      status: "not_ready",
      checks: { database: "unavailable" },
    });
    expect(JSON.stringify(result.body)).not.toMatch(
      /secret|ECONNREFUSED|db\.internal|stack/i,
    );
  });

  it("returns not_ready when DATABASE_URL is missing", async () => {
    const result = await evaluateReadiness({
      connectionString: undefined,
      createClient: () => {
        throw new Error("createClient should not be called");
      },
    });

    expect(result).toEqual({
      httpStatus: 503,
      body: {
        service: "greenfield-product",
        status: "not_ready",
        checks: { database: "unavailable" },
      },
    });
  });

  it("returns unavailable when the probe times out", async () => {
    const check = await probeDatabase(
      {
        $queryRaw: async () =>
          new Promise((resolve) => {
            setTimeout(resolve, 50);
          }),
      },
      5,
    );

    expect(check).toBe("unavailable");
    expect(toReadinessResult(check)).toEqual({
      httpStatus: 503,
      body: {
        service: "greenfield-product",
        status: "not_ready",
        checks: { database: "unavailable" },
      },
    });
  });
});
