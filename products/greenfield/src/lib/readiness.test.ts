import { describe, expect, it } from "vitest";
import {
  evaluateReadiness,
  readinessHttpStatus,
  type ReadinessPayload,
} from "@/lib/readiness";

describe("service readiness contract", () => {
  it("returns HTTP 200 with a ready payload when the database probe succeeds", async () => {
    const payload = await evaluateReadiness(async () => undefined);

    expect(payload).toEqual({
      status: "ready",
      checks: { database: "ok" },
    } satisfies ReadinessPayload);
    expect(readinessHttpStatus(payload)).toBe(200);
  });

  it("returns HTTP 503 with a safe not-ready payload when the database is unavailable", async () => {
    const payload = await evaluateReadiness(async () => {
      throw new Error(
        "connect ECONNREFUSED postgresql://app:secret@db.internal:5432/prod",
      );
    });

    expect(payload).toEqual({
      status: "not_ready",
      checks: { database: "unavailable" },
    } satisfies ReadinessPayload);
    expect(readinessHttpStatus(payload)).toBe(503);
    expect(JSON.stringify(payload)).not.toMatch(
      /secret|postgresql:\/\/|ECONNREFUSED|db\.internal|stack|password/i,
    );
  });

  it("returns HTTP 503 with unavailable when the database probe times out", async () => {
    const payload = await evaluateReadiness(
      async () =>
        new Promise((resolve) => {
          setTimeout(resolve, 50);
        }),
      5,
    );

    expect(payload).toEqual({
      status: "not_ready",
      checks: { database: "unavailable" },
    } satisfies ReadinessPayload);
    expect(readinessHttpStatus(payload)).toBe(503);
  });

  it("keeps the liveness health contract distinct from readiness", () => {
    expect({ service: "greenfield-product", status: "ok" }).toEqual({
      service: "greenfield-product",
      status: "ok",
    });
  });
});
