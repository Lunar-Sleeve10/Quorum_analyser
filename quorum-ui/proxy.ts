import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

// Redirect the root path to the cover page unless the user has already entered
// the dashboard (tracked via a cookie set by the cover page's gotoDashboard()).
export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/") {
    const entered = request.cookies.get("quorum_entered")
    if (!entered) {
      return NextResponse.redirect(new URL("/cover", request.url))
    }
  }
  return NextResponse.next()
}

export const config = {
  matcher: ["/"],
}
