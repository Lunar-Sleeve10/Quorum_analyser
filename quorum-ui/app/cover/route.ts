import { NextResponse } from "next/server"
import { readFileSync } from "fs"
import { join } from "path"

// Serves public/cover.html with API_BASE injected from the environment.
// This makes the cover page work on Vercel (pointing at the Render backend)
// without hardcoding localhost in a static file.
export function GET() {
  // Strip trailing slash so the cover's `API_BASE + "/path"` never yields "//".
  const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "")
  const html = readFileSync(join(process.cwd(), "public", "cover.html"), "utf-8").replace(
    /const API_BASE\s*=\s*"[^"]*";/,
    `const API_BASE = "${apiBase}";`,
  )
  return new NextResponse(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  })
}
