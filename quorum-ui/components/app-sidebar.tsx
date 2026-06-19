"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const items: [string, string][] = [
  ["/", "Dashboard"],
  ["/investigations", "Investigations"],
  ["/insights", "Insights"],
  ["/audit", "Audit Trail"],
  ["/data-sources", "Data Sources"],
  ["/system", "System Status"],
]

export function AppSidebar() {
  const path = usePathname()
  return (
    <aside className="hidden md:block w-56 shrink-0 border-r border-border h-screen sticky top-0 p-4">
      <div className="text-lg font-medium">Quorum</div>
      <div className="text-xs text-muted-foreground mb-6">Governed Analytics Review Board</div>
      <nav className="flex flex-col gap-1">
        {items.map(([href, label]) => {
          const active = path === href || (href !== "/" && path.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={
                active
                  ? "rounded-md px-3 py-2 text-sm bg-accent text-accent-foreground"
                  : "rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent/50"
              }
            >
              {label}
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
