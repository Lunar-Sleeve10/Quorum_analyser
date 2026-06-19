"use client"

import { useQuota } from "@/hooks/use-api"

export function AppHeader() {
  const q = useQuota()
  return (
    <header className="sticky top-0 z-10 -mx-6 mb-6 border-b border-border bg-background/80 px-6 py-3 backdrop-blur">
      <div className="flex items-center justify-between gap-4">
        <span className="text-xs text-muted-foreground">
          Preview — AI/ML and Featherless usage is credit-limited; some investigations may be rate-limited.
        </span>
        <span className="text-xs text-muted-foreground">
          Queries remaining:{" "}
          <span className="text-foreground">
            {q.data?.queries_remaining ?? "—"} / {q.data?.queries_limit ?? "—"}
          </span>
        </span>
      </div>
    </header>
  )
}
