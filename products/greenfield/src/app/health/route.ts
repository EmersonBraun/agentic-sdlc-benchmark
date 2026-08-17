import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json({ service: "greenfield-product", status: "ok" });
}

