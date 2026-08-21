import { NextResponse } from "next/server";

import { createPrismaClient } from "@/lib/db";
import { evaluateReadiness } from "@/lib/readiness";

export const runtime = "nodejs";

/**
 * Deployment-facing readiness probe.
 *
 * Ready: HTTP 200
 * { "service":"greenfield-product","status":"ready","checks":{"database":"ok"} }
 *
 * Not ready: HTTP 503
 * { "service":"greenfield-product","status":"not_ready","checks":{"database":"unavailable"} }
 *
 * Performs a live read-only Prisma `SELECT 1` against PostgreSQL with a short
 * timeout. Failure responses are redacted and never include credentials,
 * connection strings, stack traces, or raw Prisma errors.
 */
export async function GET() {
  const { httpStatus, body } = await evaluateReadiness({
    connectionString: process.env.DATABASE_URL,
    createClient: createPrismaClient,
  });

  return NextResponse.json(body, { status: httpStatus });
}
