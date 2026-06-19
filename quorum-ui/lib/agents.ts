export interface AgentMeta {
  initials: string
  color: string
}

const ROLE_COLORS: [string, string][] = [
  ["supervisor", "#6366f1"],
  ["planner", "#6366f1"],
  ["orchestrator", "#6366f1"],
  ["sql", "#3b82f6"],
  ["analyst", "#3b82f6"],
  ["engineer", "#3b82f6"],
  ["cost", "#f59e0b"],
  ["sentinel", "#f59e0b"],
  ["guardian", "#8b5cf6"],
  ["governance", "#8b5cf6"],
  ["reviewer", "#8b5cf6"],
  ["reporter", "#14b8a6"],
  ["reporting", "#14b8a6"],
  ["decision", "#14b8a6"],
  ["investigator", "#22c55e"],
  ["adjudicator", "#f43f5e"],
  ["user", "#64748b"],
]

const DISPLAY: [string, string][] = [
  ["orchestrator", "Supervisor"],
  ["planner", "Supervisor"],
  ["supervisor", "Supervisor"],
  ["sql_engineer", "SQL Analyst"],
  ["sql_analyst", "SQL Analyst"],
  ["sql", "SQL Analyst"],
  ["analyst", "SQL Analyst"],
  ["cost", "Cost Sentinel"],
  ["sentinel", "Cost Sentinel"],
  ["reviewer", "Governance Guardian"],
  ["guardian", "Governance Guardian"],
  ["governance", "Governance Guardian"],
  ["reporting_agent", "Decision Reporter"],
  ["reporting", "Decision Reporter"],
  ["decision_reporter", "Decision Reporter"],
  ["reporter", "Decision Reporter"],
  ["investigator", "Investigator"],
  ["adjudicator", "Adjudicator"],
]

export function displayName(name: string): string {
  const n = (name || "").split("/").pop()?.toLowerCase() ?? ""
  return DISPLAY.find(([k]) => n.includes(k))?.[1] ?? (name || "Agent")
}

export function agentMeta(name: string): AgentMeta {
  const n = (name || "Agent").split("/").pop()?.toLowerCase() ?? "agent"
  const color = ROLE_COLORS.find(([k]) => n.includes(k))?.[1] ?? "#64748b"
  const label = displayName(name)
  const initials = label
    .split(/[\s_-]+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()
  return { initials, color }
}

export type EventKind =
  | "join" | "recruit" | "handoff" | "challenge" | "review"
  | "approve" | "reject" | "adjudication" | "finding" | "report" | "message"

export function classify(kind: string, summary: string): EventKind {
  const s = (summary || "").toLowerCase()
  if (s.includes("recruit")) return "recruit"
  if (s.includes("online") || s.includes("joined") || s.includes("fan-out") || s.includes("fan out")) return "join"
  if (kind === "RevisionRequest" || s.includes("challenge") || s.includes("revise")) return "challenge"
  if (s.includes("reject")) return "reject"
  if (kind === "ValidatedResult" || s.includes("pass") || s.includes("approved") || s.includes("cleared")) return "approve"
  if (kind === "BoardDecision" || s.includes("verdict")) return "adjudication"
  if (kind === "InvestigatorFinding" || s.includes("finding")) return "finding"
  if (kind === "FinalReport" || s.includes("report")) return "report"
  if (kind === "SQLResult" || s.includes("cost") || s.includes("sql")) return "review"
  return "message"
}

export const EVENT_LABEL: Record<EventKind, string> = {
  join: "joined", recruit: "recruited", handoff: "handoff", challenge: "challenge",
  review: "review", approve: "approved", reject: "rejected", adjudication: "verdict",
  finding: "finding", report: "report", message: "message",
}

export const EVENT_TONE: Record<EventKind, string> = {
  join: "text-emerald-600", recruit: "text-indigo-600", handoff: "text-muted-foreground",
  challenge: "text-amber-600", review: "text-blue-600", approve: "text-emerald-600",
  reject: "text-rose-600", adjudication: "text-violet-600", finding: "text-green-600",
  report: "text-teal-600", message: "text-muted-foreground",
}