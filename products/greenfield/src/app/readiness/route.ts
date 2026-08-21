import { NextResponse } from "next/server";
import { evaluateReadiness } from "@/lib/readiness";

export const runtime = "nodejs";

/**
 * Deployment-facing readiness probe.
 *
 * Ready: HTTP 200 { "status": "ready", "checks": { "database": "ok" } }
 * Not ready: HTTP 503 { "status": "not_ready", "checks": { "database": "unavailable" } }
 *
 * Performs a live read-only Prisma `SELECT 1` against PostgreSQL with a short
 * timeout. Failure responses are redacted and never include credentials,
 * connection strings, stack traces, or raw Prisma errors.
 */
export async function GET() {
  const { status, body } = await evaluateReadiness();
  return NextResponse.json(body, { status });
}
