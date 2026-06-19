"use client"

import { useState } from "react"
import type { ComponentType, ReactNode } from "react"
import type { CostInfo } from "@/lib/types"
import { DollarSign, Rows3, Shield, Zap, Code2, Info } from "lucide-react"
import { cn } from "@/lib/utils"

function Metric({
  icon: Icon,
  label,
  value,
  description,
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  value: ReactNode
  description?: string
}) {
  return (
    <div className="group relative space-y-1">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
        {description && (
          <span className="cursor-help">
            <Info className="h-2.5 w-2.5 text-muted-foreground/50" />
            <span className="pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 w-48 rounded-lg border border-border bg-popover p-2 text-xs text-muted-foreground shadow-lg opacity-0 group-hover:opacity-100 transition-opacity">
              {description}
            </span>
          </span>
        )}
      </div>
      <div className="text-sm font-medium text-foreground">{value}</div>
    </div>
  )
}

const RISK_CONFIG = {
  low: { classes: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Low Risk" },
  medium: { classes: "bg-amber-50 text-amber-700 border-amber-200", label: "Medium Risk" },
  high: { classes: "bg-rose-50 text-rose-700 border-rose-200", label: "High Risk" },
}

export function CostPanel({
  cost,
  topology,
  sql,
}: {
  cost: CostInfo | null
  topology: string
  sql?: string | null
}) {
  const [sqlExpanded, setSqlExpanded] = useState(false)
  const e = cost?.estimate
  const rawRisk = (cost?.risk_level ?? e?.risk_level ?? "").toLowerCase()
  const riskConfig =
    RISK_CONFIG[rawRisk as keyof typeof RISK_CONFIG] ?? {
      classes: "bg-muted text-muted-foreground border-border",
      label: rawRisk || "Unknown",
    }

  const tables = sql
    ? Array.from(
        new Set(
          [...sql.matchAll(/(?:from|join)\s+([A-Za-z_]\w*)/gi)].map(m => m[1]),
        ),
      )
    : []

  const complexity =
    topology === "investigation_board" ? "Diagnostic · parallel" : "Descriptive · linear"

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 px-4 pt-4 pb-3 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-amber-500" />
            <span className="text-sm font-semibold text-foreground">Cost Sentinel</span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Validates SQL quality, execution efficiency, and compliance with the approved analysis plan.
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
            riskConfig.classes,
          )}
        >
          {riskConfig.label}
        </span>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4">
        <Metric
          icon={DollarSign}
          label="Est. cost"
          value={
            e?.estimated_cost_usd != null
              ? `$${e.estimated_cost_usd}`
              : "—"
          }
          description="Estimated query execution cost in USD."
        />
        <Metric
          icon={Rows3}
          label="Rows scanned"
          value={e?.estimated_rows_scanned?.toLocaleString() ?? "—"}
          description="Approximate number of rows the query will scan."
        />
        <Metric
          icon={Zap}
          label="Complexity"
          value={complexity}
        />
        <Metric
          icon={Code2}
          label="Tables"
          value={tables.length > 0 ? tables.join(", ") : "—"}
          description="Database tables accessed by the generated query."
        />
      </div>

      {/* SQL reveal */}
      {sql && (
        <div className="border-t border-border">
          <button
            onClick={() => setSqlExpanded(v => !v)}
            className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
          >
            <span className="font-medium">View generated SQL</span>
            <Code2 className={cn("h-3.5 w-3.5 transition-transform", sqlExpanded && "rotate-180")} />
          </button>
          {sqlExpanded && (
            <pre className="overflow-x-auto bg-muted/30 px-4 pb-4 pt-2 text-[11px] font-mono text-foreground/80 leading-relaxed">
              {sql}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
