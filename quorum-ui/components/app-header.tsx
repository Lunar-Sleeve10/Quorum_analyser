"use client"

import { useQuota } from "@/hooks/use-api"
import { Zap } from "lucide-react"
import { cn } from "@/lib/utils"

export function AppHeader() {
  const q = useQuota()
  const remaining = q.data?.queries_remaining ?? null
  const limit = q.data?.queries_limit ?? null

  const pct = remaining != null && limit != null && limit > 0 ? remaining / limit : null
  const lowQuota = pct != null && pct < 0.2

  return (
    <header className="sticky top-0 z-10 -mx-6 mb-6 border-b border-border bg-background/90 px-6 py-3 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-muted-foreground hidden sm:block">
          Preview — AI/ML usage is credit-limited; some investigations may be rate-limited.
        </p>

        {/* Quota indicator */}
        <div className={cn(
          "ml-auto flex items-center gap-2 rounded-full border px-3 py-1",
          lowQuota
            ? "border-amber-200 bg-amber-50 text-amber-700"
            : "border-border bg-muted/40 text-muted-foreground",
        )}>
          <Zap className={cn("h-3 w-3", lowQuota && "text-amber-500")} />
          <span className="text-xs font-medium">
            {remaining ?? "—"}
            <span className="font-normal opacity-60"> / {limit ?? "—"} queries</span>
          </span>
        </div>
      </div>
    </header>
  )
}
