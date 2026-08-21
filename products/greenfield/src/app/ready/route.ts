import { NextResponse } from "next/server";

import { createPrismaClient } from "@/lib/db";
import { evaluateReadiness } from "@/lib/readiness";

export async function GET() {
  const { httpStatus, body } = await evaluateReadiness({
    connectionString: process.env.DATABASE_URL,
    createClient: createPrismaClient,
  });

  return NextResponse.json(body, { status: httpStatus });
}
