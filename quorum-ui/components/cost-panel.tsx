import type { CostInfo } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export function CostPanel({ cost, topology, sql }: { cost: CostInfo | null; topology: string; sql?: string | null }) {
  const e = cost?.estimate
  const tables = sql
    ? Array.from(new Set([...sql.matchAll(/(?:from|join)\s+([A-Za-z_]\w*)/gi)].map((m) => m[1])))
    : []
  const risk = cost?.risk_level ?? e?.risk_level ?? "—"
  const complexity = topology === "investigation_board" ? "Diagnostic · parallel" : "Descriptive · linear"
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">Cost Sentinel</CardTitle></CardHeader>
      <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div><div className="text-xs text-muted-foreground">Risk</div><Badge variant={risk === "high" ? "destructive" : "secondary"}>{risk}</Badge></div>
        <div><div className="text-xs text-muted-foreground">Est. cost</div><div>{e?.estimated_cost_usd != null ? `$${e.estimated_cost_usd}` : "—"}</div></div>
        <div><div className="text-xs text-muted-foreground">Rows scanned</div><div>{e?.estimated_rows_scanned ?? "—"}</div></div>
        <div><div className="text-xs text-muted-foreground">Complexity</div><div>{complexity}</div></div>
        <div className="col-span-2 md:col-span-4"><div className="text-xs text-muted-foreground">Tables touched</div><div>{tables.length ? tables.join(", ") : "—"}</div></div>
      </CardContent>
    </Card>
  )
}
