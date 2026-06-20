"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { CostPanel } from "@/components/cost-panel"
import { ResultView } from "@/components/result-view"
import { TopologyBadge } from "@/components/topology-badge"
import { StatusBadge } from "@/components/status-badge"
import type { InvestigationDetail } from "@/lib/types"

function summary(inv: InvestigationDetail): string {
  if (inv.board_decision?.headline) return inv.board_decision.headline
  const ar = inv.authorized_result
  if (ar && ar.row_count) {
    const cols = ar.columns?.join(", ")
    return `The governed query returned ${ar.row_count.toLocaleString()} row(s) across ${ar.columns?.length ?? 0} field(s): ${cols}.`
  }
  return "Awaiting the governed result."
}

function confidencePct(c: number | null): string | null {
  if (c == null) return null
  return `${Math.round(c * 100)}%`
}

export function ReportView({ inv, done }: { inv: InvestigationDetail; done: boolean }) {
  const conf = confidencePct(inv.confidence)
  return (
    <div className="space-y-4">
      {/* Cover / header */}
      <Card className="overflow-hidden">
        <div className="h-1 w-full bg-gradient-to-r from-indigo-500 via-violet-500 to-teal-500" />
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">Executive report</CardTitle>
            <TopologyBadge t={inv.topology} />
            <StatusBadge s={inv.status} />
            {conf && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">confidence {conf}</span>}
            {inv.created_at && <span className="ml-auto text-xs text-muted-foreground">{inv.created_at.slice(0, 10)}</span>}
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Question</p>
            <p className="text-base font-medium">{inv.normalized_question || inv.question}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Executive summary</p>
            <p className="leading-relaxed whitespace-pre-line">{inv.analysis?.narrative || summary(inv)}</p>
          </div>
          {(inv.board_decision?.recommendation || inv.analysis?.recommended_action) && (
            <div className="rounded-md border border-indigo-200 bg-indigo-50/60 p-3 dark:border-indigo-900 dark:bg-indigo-950/30">
              <p className="text-xs font-semibold uppercase tracking-wide text-indigo-700 dark:text-indigo-300">Recommended action</p>
              <p className="mt-0.5">{inv.board_decision?.recommendation || inv.analysis?.recommended_action}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Analysis (finding + implication) */}
      {inv.analysis && (inv.analysis.finding || inv.analysis.implication) && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Analysis</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {inv.analysis.finding && (
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Finding</p>
                <p className="leading-relaxed">{inv.analysis.finding}</p>
              </div>
            )}
            {inv.analysis.implication && (
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Implication</p>
                <p className="leading-relaxed">{inv.analysis.implication}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Verdict (diagnostic) */}
      {inv.board_decision && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Board verdict</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="font-medium">{inv.board_decision.headline}</p>
            {inv.board_decision.primary_factor && (
              <p>Primary driver: <span className="font-medium">{inv.board_decision.primary_factor}</span></p>
            )}
            {inv.findings.length > 0 && (
              <div className="space-y-1 pt-1">
                {inv.findings.map((f, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="font-medium">{f.label}</span>
                    <span className="text-muted-foreground">— {f.evidence}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Findings & visualizations */}
      {inv.authorized_result ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Findings &amp; visualizations</CardTitle></CardHeader>
          <CardContent><ResultView result={inv.authorized_result} /></CardContent>
        </Card>
      ) : !inv.board_decision ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            {done ? "No result was produced for this investigation." : "Working… the agents are collaborating."}
          </CardContent>
        </Card>
      ) : null}

      {/* Governance / cost */}
      <CostPanel cost={inv.cost} topology={inv.topology} sql={inv.sql} />
      <p className="px-1 text-xs text-muted-foreground">
        Governed by construction: the database is opened read-only — every query is analysis-only
        (SELECT with joins, window functions, and partitioning). No statement can modify data.
      </p>
    </div>
  )
}
