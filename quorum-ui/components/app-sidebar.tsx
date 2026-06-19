"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  Search,
  TrendingUp,
  BookOpen,
  Database,
  Activity,
} from "lucide-react"
import { cn } from "@/lib/utils"

const items: [string, string, React.ComponentType<{ className?: string }>][] = [
  ["/", "Dashboard", LayoutDashboard],
  ["/investigations", "Investigations", Search],
  ["/insights", "Insights", TrendingUp],
  ["/audit", "Audit Trail", BookOpen],
  ["/data-sources", "Data Sources", Database],
  ["/system", "System", Activity],
]

export function AppSidebar() {
  const path = usePathname()

  return (
    <aside className="hidden md:flex md:flex-col w-56 shrink-0 border-r border-border h-screen sticky top-0">
      {/* Branding */}
      <div className="px-4 pt-5 pb-4 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground text-xs font-bold">
            Q
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">Quorum</div>
            <div className="text-[10px] text-muted-foreground leading-tight">AI Analyst Workspace</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto p-3 space-y-0.5">
        <div className="pb-1 pt-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
          Workspace
        </div>
        {items.map(([href, label, Icon]) => {
          const active = path === href || (href !== "/" && path.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all",
                active
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-colors",
                  active ? "text-foreground" : "text-muted-foreground group-hover:text-foreground",
                )}
              />
              {label}
              {active && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-border">
        <div className="rounded-lg bg-muted/50 px-3 py-2.5">
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            Governed multi-agent analytics. Each analysis goes through planning, governance review, and validation before delivering results.
          </p>
        </div>
      </div>
    </aside>
  )
}
