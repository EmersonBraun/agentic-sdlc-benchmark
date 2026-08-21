import { NextResponse } from "next/server";
import {
  evaluateReadiness,
  readinessHttpStatus,
} from "@/lib/readiness";

export async function GET() {
  const payload = await evaluateReadiness();
  return NextResponse.json(payload, { status: readinessHttpStatus(payload) });
}
