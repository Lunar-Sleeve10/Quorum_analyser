"use client"

import { use, useState } from "react"
import Link from "next/link"
import { motion, AnimatePresence } from "motion/react"
import { useFollowup, useInvestigation, useRoom } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { TopologyBadge } from "@/components/topology-badge"
import { StatusBadge } from "@/components/status-badge"
import { ResultView } from "@/components/result-view"
import { CostPanel } from "@/components/cost-panel"
import { AgentRoom } from "@/components/agent-room"
import { ReportActions } from "@/components/report-actions"
import { WorkflowTimeline } from "@/components/workflow-timeline"
import { ScrollReveal } from "@/components/motion/scroll-reveal"
import { ShimmerCard, CyclingText } from "@/components/motion/shimmer"
import {
  Star,
  StarOff,
  ChevronDown,
  ChevronUp,
  Info,
  ArrowLeft,
  CheckCircle2,
  AlertCircle,
  Link2,
  ChevronRight,
  Radio,
} from "lucide-react"
import { cn } from "@/lib/utils"

/* ── Skeleton loader ─────────────────────────────────────────────────── */

function InvestigationSkeleton() {
  return (
    <div className="space-y-4 pt-2 animate-pulse">
      <div className="h-8 w-2/3 rounded-lg bg-muted" />
      <div className="h-4 w-1/3 rounded-md bg-muted" />
      <div className="h-28 rounded-xl bg-muted" />
      <div className="h-40 rounded-xl bg-muted" />
      <div className="h-72 rounded-xl bg-muted" />
    </div>
  )
}

/* ── Section header ──────────────────────────────────────────────────── */

function SectionHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {description && (
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}

/* ── Live pill ───────────────────────────────────────────────────────── */

function LivePill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-600 px-2.5 py-1 text-xs font-medium text-violet-50 dark:bg-violet-500 dark:text-white">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-300 opacity-75" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-300" />
      </span>
      Live investigation
    </span>
  )
}

/* ── Board verdict ───────────────────────────────────────────────────── */

function BoardVerdict({ inv }: { inv: ReturnType<typeof useInvestigation>["data"] }) {
  const [findingsOpen, setFindingsOpen] = useState(false)
  if (!inv?.board_decision) return null
  const d = inv.board_decision

  return (
    <div className="space-y-3">
      {/* Headline */}
      <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
        <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600 mt-0.5" />
        <div className="space-y-1">
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
            Board Verdict
          </div>
          <p className="text-sm font-semibold text-foreground leading-snug">{d.headline}</p>
          {d.confidence && (
            <span className="text-xs text-muted-foreground">
              Confidence: {d.confidence}
            </span>
          )}
        </div>
      </div>

      {/* Primary factor */}
      {d.primary_factor && (
        <div className="rounded-lg border border-border bg-card px-4 py-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Primary driver
          </div>
          <p className="text-sm text-foreground">{d.primary_factor}</p>
        </div>
      )}

      {/* Recommendation */}
      {d.recommendation && (
        <div className="rounded-lg border border-border bg-card px-4 py-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Recommendation
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">{d.recommendation}</p>
        </div>
      )}

      {/* Findings */}
      {inv.findings.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <button
            onClick={() => setFindingsOpen(v => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-xs hover:bg-muted/40 transition-colors"
          >
            <span className="font-semibold text-foreground">
              View {inv.findings.length} supporting finding{inv.findings.length > 1 ? "s" : ""}
            </span>
            {findingsOpen ? (
              <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>
          <AnimatePresence initial={false}>
            {findingsOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="border-t border-border divide-y divide-border">
                  {inv.findings.map((f, i) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          {f.factor}
                        </span>
                        <span className={cn(
                          "text-[9px] font-semibold uppercase rounded-full px-1.5 py-0.5",
                          f.verdict?.toLowerCase().includes("confirm") || f.verdict?.toLowerCase().includes("yes")
                            ? "bg-emerald-100 text-emerald-700"
                            : f.verdict?.toLowerCase().includes("no") || f.verdict?.toLowerCase().includes("reject")
                              ? "bg-rose-100 text-rose-700"
                              : "bg-muted text-muted-foreground",
                        )}>
                          {f.verdict}
                        </span>
                      </div>
                      <p className="text-xs text-foreground">{f.label}</p>
                      {f.evidence && (
                        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{f.evidence}</p>
                      )}
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

/* ── Governance audit ────────────────────────────────────────────────── */

function AuditTrail({ events }: { events: Array<{ type: string; ts: string | null; detail: Record<string, unknown> }> }) {
  const [open, setOpen] = useState(false)
  if (events.length === 0) return null

  const revisions = events.filter(e =>
    (e.type || "").toLowerCase().includes("revision") ||
    (e.type || "").toLowerCase().includes("challenge"),
  ).length

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground">Governance Audit Trail</span>
          <span className="text-[10px] text-muted-foreground">
            {events.length} event{events.length > 1 ? "s" : ""}
          </span>
          {revisions > 0 && (
            <span className="text-[9px] bg-amber-100 border border-amber-200 text-amber-700 rounded-full px-1.5 py-0.5 font-semibold">
              {revisions} revision{revisions > 1 ? "s" : ""}
            </span>
          )}
        </div>
        {open ? (
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-border divide-y divide-border">
              {events.map((g, i) => (
                <div key={i} className="flex items-start gap-3 px-4 py-2.5">
                  <span className="font-mono text-[10px] text-muted-foreground pt-0.5 shrink-0 w-16">
                    {(g.ts ?? "").slice(11, 19)}
                  </span>
                  <div>
                    <span className="text-xs font-medium text-foreground">{g.type}</span>
                    {g.detail && Object.keys(g.detail).length > 0 && (
                      <p className="text-[10px] text-muted-foreground mt-0.5 leading-relaxed">
                        {Object.entries(g.detail)
                          .slice(0, 2)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ── Page ────────────────────────────────────────────────────────────── */

export default function InvestigationDetail({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const q = useInvestigation(id)
  const room = useRoom(id)
  const followup = useFollowup(id)
  const saved = useSession(s => s.saved)
  const toggleSaved = useSession(s => s.toggleSaved)
  const [text, setText] = useState("")
  const inv = q.data

  if (!inv) return <InvestigationSkeleton />

  const live = inv.status === "planning" || inv.status === "running"
  const canFollow = inv.followups_used < 2
  const messages = room.data?.messages ?? []
  const hasResult = !!(inv.board_decision || inv.authorized_result)

  return (
    <div className="space-y-6 pb-12">

      {/* ── 1. Investigation header ────────────────────────────────────── */}
      <ScrollReveal>
        <div className="space-y-3">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Link href="/investigations" className="hover:text-foreground transition-colors flex items-center gap-1">
              <ArrowLeft className="h-3 w-3" />
              Investigations
            </Link>
            <ChevronRight className="h-3 w-3" />
            <span className="text-foreground font-medium">Detail</span>
          </div>

          {/* Badges + actions row */}
          <div className="flex flex-wrap items-center gap-2">
            <TopologyBadge t={inv.topology} />
            <StatusBadge s={inv.status} />
            {inv.confidence != null && (
              <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-xs text-muted-foreground">
                <Info className="h-3 w-3" />
                {Math.round(Number(inv.confidence) * 100)}% confidence
              </span>
            )}
            <button
              onClick={() => toggleSaved(inv.id)}
              className="ml-auto flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
            >
              {saved.includes(inv.id) ? (
                <><Star className="h-3 w-3 fill-amber-400 text-amber-400" />Saved</>
              ) : (
                <><StarOff className="h-3 w-3" />Save</>
              )}
            </button>
          </div>

          {/* Question */}
          <h1 className="text-xl font-semibold text-foreground leading-snug">
            {inv.normalized_question || inv.question}
          </h1>

          {/* Follow-up of parent */}
          {inv.parent_investigation_id && (
            <Link
              href={`/investigations/${inv.parent_investigation_id}`}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <Link2 className="h-3 w-3" />
              Follow-up of a prior investigation
            </Link>
          )}
        </div>
      </ScrollReveal>

      {/* ── 2. Execution pipeline ──────────────────────────────────────── */}
      <ScrollReveal delay={0.04}>
        <WorkflowTimeline inv={inv} />
      </ScrollReveal>

      {/* ── 3. Agent Room ─────────────────────────────────────────────── */}
      <ScrollReveal delay={0.08}>
        <div
          className={cn(
            "rounded-xl border p-4 transition-colors duration-300",
            live
              ? "border-violet-300 bg-violet-50/40 dark:border-violet-800 dark:bg-violet-950/30"
              : "border-border bg-card"
          )}
        >
          <SectionHeader
            title="Agent Room"
            description={
              live
                ? "This is where the investigation runs — watch each AI specialist decide, revise, and produce findings in real time."
                : "Decisions, revisions, and outputs generated by each AI specialist."
            }
            action={live ? <LivePill /> : undefined}
          />
          <AgentRoom
            investigationId={inv.id}
            initial={messages}
            agents={room.data?.active_agents ?? []}
            done={!live}
          />
        </div>
      </ScrollReveal>

      {/* ── 4. Loading state (no result yet) ──────────────────────────── */}
      {!hasResult && live && (
        <ScrollReveal delay={0.1}>
          <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/20 px-5 py-4">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
            </span>
            <div>
              <CyclingText className="text-sm text-muted-foreground font-medium" />
              <p className="text-xs text-muted-foreground/60 mt-0.5">
                Results will appear here once all review stages complete.
              </p>
            </div>
          </div>
        </ScrollReveal>
      )}

      {/* ── 5. Intelligence Brief (board verdict or data result) ───────── */}
      {hasResult && (
        <ScrollReveal delay={0.12}>
          <div className="rounded-xl border border-border bg-card p-4">
            <SectionHeader
              title="Analysis Results"
              description="Final validated findings generated after all review stages completed."
            />
            {inv.board_decision ? (
              <BoardVerdict inv={inv} />
            ) : inv.authorized_result ? (
              <ResultView result={inv.authorized_result} />
            ) : null}
          </div>
        </ScrollReveal>
      )}

      {/* ── 6. Governance Intelligence ────────────────────────────────── */}
      <ScrollReveal delay={0.16}>
        <div className="space-y-3">
          <SectionHeader
            title="Governance Intelligence"
            description="Quality checks and safeguards applied before results were delivered."
          />
          <CostPanel cost={inv.cost} topology={inv.topology} sql={inv.sql} />
          <AuditTrail events={inv.governance} />
        </div>
      </ScrollReveal>

      {/* ── 7. Continue Investigation ─────────────────────────────────── */}
      <ScrollReveal delay={0.2}>
        <div className="rounded-xl border border-border bg-card p-4">
          <SectionHeader
            title="Continue Investigation"
            description="Ask a follow-up question that reuses this investigation's context, data source, and prior findings."
            action={
              <span className="text-xs text-muted-foreground shrink-0">
                {inv.followups_used} / 2 used
              </span>
            }
          />

          {/* Existing follow-ups */}
          {inv.followups.length > 0 && (
            <div className="mb-4 space-y-2">
              {inv.followups.map(f => (
                <Link
                  key={f.id}
                  href={`/investigations/${f.id}`}
                  className="flex items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-xs hover:bg-muted/40 transition-colors group"
                >
                  <StatusBadge s={f.status} />
                  <span className="flex-1 truncate text-foreground group-hover:text-foreground/80">
                    {f.question}
                  </span>
                  <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
                </Link>
              ))}
              <Separator />
            </div>
          )}

          {inv.followups.length === 0 && !canFollow && (
            <p className="text-xs text-muted-foreground mb-4">
              No follow-ups yet and the limit has been reached.
            </p>
          )}

          {inv.followups.length === 0 && canFollow && (
            <p className="text-xs text-muted-foreground mb-3">
              No follow-ups yet. Ask a deeper question below.
            </p>
          )}

          {/* Input */}
          <div className="flex items-center gap-2">
            <Input
              placeholder={
                canFollow
                  ? "Ask a deeper question about these findings…"
                  : "Follow-up limit reached (2 / 2)"
              }
              value={text}
              onChange={e => setText(e.target.value)}
              disabled={!canFollow}
              onKeyDown={async e => {
                if (e.key === "Enter" && canFollow && text.trim() && !followup.isPending) {
                  await followup.mutateAsync(text.trim())
                  setText("")
                }
              }}
            />
            <Button
              disabled={!canFollow || followup.isPending || !text.trim()}
              onClick={async () => {
                await followup.mutateAsync(text.trim())
                setText("")
              }}
            >
              {followup.isPending ? "Asking…" : "Ask"}
            </Button>
          </div>
        </div>
      </ScrollReveal>

      {/* ── 8. Export ─────────────────────────────────────────────────── */}
      <ScrollReveal delay={0.24}>
        <ReportActions inv={inv} messages={messages} />
      </ScrollReveal>
    </div>
  )
}