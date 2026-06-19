"use client"

import { Chart, cell, toLabel } from "@/lib/charts"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { analyze, type Insight } from "@/lib/viz"
import type { AuthorizedResult } from "@/lib/types"

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="truncate text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

const TONE: Record<NonNullable<Insight["kind"]>, string> = {
  up: "border-l-emerald-500", down: "border-l-rose-500", warn: "border-l-amber-500", info: "border-l-indigo-500",
}

function Insights({ items }: { items: Insight[] }) {
  if (!items.length) return null
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Key insights</div>
      <div className="grid gap-2 md:grid-cols-2">
        {items.map((it, i) => (
          <div key={i} className={`rounded-md border border-border border-l-4 ${TONE[it.kind ?? "info"]} bg-background px-3 py-2 text-sm`}>
            {it.text}
          </div>
        ))}
      </div>
    </div>
  )
}

function DataTable({ columns, rows }: { columns: string[]; rows: unknown[] }) {
  return (
    <div className="max-h-96 overflow-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>{columns.map((c) => <TableHead key={c}>{c}</TableHead>)}</TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 200).map((r, i) => (
            <TableRow key={i}>
              {columns.map((c, j) => <TableCell key={j}>{toLabel(cell(r, columns, j)) || "—"}</TableCell>)}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function ResultView({ result }: { result: AuthorizedResult }) {
  const columns = result.columns ?? []
  const rows = (result.rows ?? []) as unknown[]
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No rows returned.</p>
  const a = analyze(columns, rows)

  if (a.single !== null) {
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-6">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{columns[0]}</div>
        <div className="text-4xl font-semibold tabular-nums">{a.single}</div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {a.kpis.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {a.kpis.map((k, i) => <Kpi key={i} label={k.label} value={k.value} hint={k.hint} />)}
        </div>
      )}

      <Insights items={a.insights} />

      {a.charts.length > 0 && (
        <div className={a.charts.length > 1 ? "grid gap-4 md:grid-cols-2" : "space-y-4"}>
          {a.charts.map((c, i) => <Chart key={i} spec={c} />)}
        </div>
      )}

      <details className="rounded-md border border-border p-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground">Underlying data ({rows.length} rows · {columns.length} columns)</summary>
        <div className="mt-3"><DataTable columns={columns} rows={rows} /></div>
      </details>
    </div>
  )
}
