import { describe, expect, it, vi } from "vitest";
import { GET as getHealth } from "@/app/health/route";
import { GET as getReadiness } from "@/app/readiness/route";
import {
  READINESS_TIMEOUT_MS,
  buildReadinessBody,
  evaluateReadiness,
  probeDatabase,
  readinessHttpStatus,
} from "@/lib/readiness";

describe("health contract regression", () => {
  it("keeps the existing /health response unchanged", async () => {
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
    const body = buildReadinessBody("ok");
    expect(body).toEqual({
      status: "ready",
      checks: { database: "ok" },
    });
    expect(readinessHttpStatus(body)).toBe(200);
  });

  it("returns not_ready when the database probe fails", async () => {
    const body = buildReadinessBody("unavailable");
    expect(body).toEqual({
      status: "not_ready",
      checks: { database: "unavailable" },
    });
    expect(readinessHttpStatus(body)).toBe(503);
  });

  it("treats a live probe failure as unavailable without leaking error details", async () => {
    const secretError = new Error(
      "P1001: Can't reach database server at postgresql://app:super-secret@db:5432/prod",
    );
    const result = await probeDatabase(async () => {
      throw secretError;
    });

    expect(result).toBe("unavailable");

    const evaluated = await evaluateReadiness(async () => {
      throw secretError;
    });
    expect(evaluated.status).toBe(503);
    expect(evaluated.body).toEqual({
      status: "not_ready",
      checks: { database: "unavailable" },
    });
    expect(JSON.stringify(evaluated.body)).not.toContain("super-secret");
    expect(JSON.stringify(evaluated.body)).not.toContain("postgresql://");
    expect(JSON.stringify(evaluated.body)).not.toContain("P1001");
    expect(JSON.stringify(evaluated.body)).not.toContain("stack");
  });

  it("marks the database unavailable when the probe exceeds the timeout budget", async () => {
    const started = Date.now();
    const result = await probeDatabase(
      () => new Promise((resolve) => setTimeout(resolve, READINESS_TIMEOUT_MS + 500)),
      50,
    );
    const elapsed = Date.now() - started;

    expect(result).toBe("unavailable");
    expect(elapsed).toBeLessThan(400);
  });

  it("uses a live probe callback rather than a static process-alive check", async () => {
    const probe = vi.fn(async () => [{ "?column?": 1 }]);
    const evaluated = await evaluateReadiness(probe);

    expect(probe).toHaveBeenCalledTimes(1);
    expect(evaluated).toEqual({
      status: 200,
      body: { status: "ready", checks: { database: "ok" } },
    });
  });
});

describe("readiness route wiring", () => {
  it("exposes GET /readiness through the App Router handler", async () => {
    expect(typeof getReadiness).toBe("function");
  });
});
