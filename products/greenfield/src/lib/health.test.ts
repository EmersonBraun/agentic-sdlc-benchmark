import { describe, expect, it } from "vitest";
import { GET } from "@/app/health/route";

describe("greenfield product fixture", () => {
  it("declares the public health contract", async () => {
    const response = GET();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      service: "greenfield-product",
      status: "ok",
    });
  });
});
