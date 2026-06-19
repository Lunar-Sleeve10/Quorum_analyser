import type { InvestigationDetail, RoomMessage } from "@/lib/types"
import { analyze } from "@/lib/viz"

function metrics(inv: InvestigationDetail): string[] {
  const m: string[] = []
  m.push(`Topology: ${inv.topology === "investigation_board" ? "Investigation board" : "Governed chain"}`)
  m.push(`Status: ${inv.status}`)
  if (inv.confidence != null) m.push(`Confidence: ${inv.confidence}`)
  if (inv.risk_level) m.push(`Risk: ${inv.risk_level}`)
  const est = inv.cost?.estimate
  if (est) {
    if (est.estimated_rows_scanned != null) m.push(`Estimated rows scanned: ${est.estimated_rows_scanned}`)
    if (est.estimated_cost_usd != null) m.push(`Estimated cost: $${est.estimated_cost_usd}`)
    if (est.engine) m.push(`Engine: ${est.engine}`)
  }
  return m
}

export function buildMarkdown(inv: InvestigationDetail, messages: RoomMessage[]): string {
  const lines: string[] = []
  lines.push(`# Investigation report`)
  lines.push("")
  lines.push(`## Question`)
  lines.push(inv.normalized_question || inv.question)
  lines.push("")
  lines.push(`## Key metrics`)
  metrics(inv).forEach((x) => lines.push(`- ${x}`))
  lines.push("")
  if (inv.cost?.estimate) {
    lines.push(`## Cost estimate`)
    const e = inv.cost.estimate
    lines.push(`- Risk level: ${e.risk_level ?? inv.cost.risk_level ?? "low"}`)
    lines.push(`- Within budget: ${e.within_budget ?? true}`)
    lines.push(`- Method: ${e.method ?? "n/a"}`)
    lines.push("")
  }
  if (inv.board_decision) {
    lines.push(`## Verdict`)
    lines.push(inv.board_decision.headline)
    if (inv.board_decision.primary_factor) lines.push(`- Primary driver: ${inv.board_decision.primary_factor}`)
    lines.push("")
  }
  if (inv.findings.length) {
    lines.push(`## Findings`)
    inv.findings.forEach((f) => lines.push(`- ${f.label}: ${f.evidence}`))
    lines.push("")
  }
  if (inv.authorized_result?.rows?.length) {
    try {
      const a = analyze(inv.authorized_result.columns ?? [], inv.authorized_result.rows as unknown[])
      if (a.kpis.length) {
        lines.push(`## At a glance`)
        a.kpis.forEach((k) => lines.push(`- ${k.label}: ${k.value}${k.hint ? ` (${k.hint})` : ""}`))
        lines.push("")
      }
      if (a.insights.length) {
        lines.push(`## Key insights`)
        a.insights.forEach((it) => lines.push(`- ${it.text}`))
        lines.push("")
      }
      if (a.charts.length) {
        lines.push(`## Visualizations`)
        a.charts.forEach((c) => lines.push(`- ${c.title}${c.subtitle ? ` (${c.subtitle})` : ""} [${c.type}]`))
        lines.push("")
      }
    } catch { /* never let analysis break the export */ }
  }
  if (inv.authorized_result?.rows?.length) {
    lines.push(`## Result`)
    lines.push(`${inv.authorized_result.columns.join(" | ")}`)
    lines.push(inv.authorized_result.columns.map(() => "---").join(" | "))
    inv.authorized_result.rows.slice(0, 20).forEach((r) => lines.push(r.map((v) => String(v)).join(" | ")))
    lines.push("")
  }
  if (messages.length) {
    lines.push(`## Agent discussion summary`)
    messages.slice(0, 40).forEach((m) => lines.push(`- ${m.sender}: ${m.summary}`))
    lines.push("")
  }
  if (inv.board_decision?.recommendation) {
    lines.push(`## Recommended actions`)
    lines.push(inv.board_decision.recommendation)
    lines.push("")
  }
  return lines.join("\n")
}
