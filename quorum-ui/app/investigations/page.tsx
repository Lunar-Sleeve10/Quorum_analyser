"use client"

import { useState } from "react"
import Link from "next/link"
import { motion, AnimatePresence } from "motion/react"
import { useCreateInvestigation, useDataSources, useInvestigations, useQuota } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { TopologyBadge } from "@/components/topology-badge"
import { StatusBadge } from "@/components/status-badge"
import { ScrollReveal } from "@/components/motion/scroll-reveal"
import { ChevronRight, Database, Sparkles, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"

/* ── Skeleton loader ─────────────────────────────────────────────────── */

function InvestigationsListSkeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      {[72, 56, 64, 56].map((w, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-border px-3 py-3">
          <div className="h-2 w-2 rounded-full bg-muted shrink-0" />
          <div className="flex-1 space-y-1.5">
            <div className={`h-3 rounded-md bg-muted`} style={{ width: `${w}%` }} />
            <div className="flex gap-1.5">
              <div className="h-4 w-12 rounded-full bg-muted" />
              <div className="h-4 w-14 rounded-full bg-muted" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Quota bar ───────────────────────────────────────────────────────── */

function QuotaBar({
  used,
  limit,
}: {
  used: number
  limit: number
}) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0
  const low = pct >= 80

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Queries remaining</span>
        <span className={cn("text-xs font-medium tabular-nums", low ? "text-amber-600" : "text-foreground")}>
          {limit - used} / {limit}
        </span>
      </div>
      <div className="h-1 rounded-full bg-muted overflow-hidden">
        <motion.div
          className={cn("h-full rounded-full", low ? "bg-amber-400" : "bg-primary")}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
    </div>
  )
}

/* ── Single investigation row ────────────────────────────────────────── */

function InvestigationRow({
  inv,
  index,
}: {
  inv: {
    id: string
    question: string
    topology: string
    status: string
    created_at?: string | null
  }
  index: number
}) {
  const live = inv.status === "running" || inv.status === "planning"
  const done = inv.status === "complete" || inv.status === "authorized"

  const dotClass = live
    ? "bg-violet-500 animate-pulse"
    : done
      ? "bg-emerald-500"
      : "bg-muted-foreground/40"

  const relativeTime = (ts?: string) => {
    if (!ts) return null
    const diff = Date.now() - new Date(ts).getTime()
    const m = Math.floor(diff / 60000)
    if (m < 1) return "just now"
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
    >
      <Link
        href={`/investigations/${inv.id}`}
        className={cn(
          "group flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors",
          live
            ? "border-violet-200 bg-violet-50/60 hover:bg-violet-100/50 dark:border-violet-800 dark:bg-violet-950/30 dark:hover:bg-violet-900/30"
            : "border-border hover:bg-muted/40"
        )}
      >
        {/* Status dot */}
        <span className={cn("h-2 w-2 shrink-0 rounded-full mt-0.5", dotClass)} />

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              "truncate text-sm leading-snug",
              live
                ? "font-medium text-violet-900 dark:text-violet-200"
                : "text-foreground"
            )}
          >
            {inv.question}
          </p>
          <div className="mt-1.5 flex items-center gap-1.5">
            <TopologyBadge t={inv.topology} />
            <StatusBadge s={inv.status} />
            {live && (
              <span className="inline-flex items-center gap-1 rounded-full bg-violet-600 px-2 py-0.5 text-[10px] font-medium text-violet-50">
                <span className="h-1 w-1 rounded-full bg-violet-200 animate-pulse" />
                Live
              </span>
            )}
          </div>
        </div>

        {/* Timestamp + chevron */}
        <div className="flex items-center gap-1.5 shrink-0">
          {inv.created_at && (
            <span className="text-[11px] text-muted-foreground hidden sm:block">
              {relativeTime(inv.created_at)}
            </span>
          )}
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
        </div>
      </Link>
    </motion.div>
  )
}

/* ── Empty state ─────────────────────────────────────────────────────── */

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-muted/40">
        <Sparkles className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium text-foreground">No investigations yet</p>
      <p className="text-xs text-muted-foreground max-w-[220px] leading-relaxed">
        Ask your first question above and an AI board will investigate it for you.
      </p>
    </div>
  )
}

/* ── Page ────────────────────────────────────────────────────────────── */

export default function InvestigationsPage() {
  const inv = useInvestigations()
  const ds = useDataSources()
  const quota = useQuota()
  const create = useCreateInvestigation()
  const setCurrent = useSession((s) => s.setCurrent)
  const [question, setQuestion] = useState("")
  const [source, setSource] = useState("")

  const submit = async () => {
    if (!question.trim()) return
    const r = await create.mutateAsync({ question: question.trim(), dataSourceId: source || null })
    setCurrent(r.id)
    setQuestion("")
  }

  const top = (inv.data ?? []).filter((i) => !i.parent_investigation_id)

  // Sort: live first, then by recency
  const sorted = [...top].sort((a, b) => {
    const aLive = a.status === "running" || a.status === "planning" ? 1 : 0
    const bLive = b.status === "running" || b.status === "planning" ? 1 : 0
    if (aLive !== bLive) return bLive - aLive
    return new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()
  })

  const quotaUsed =
    quota.data && quota.data.queries_limit != null && quota.data.queries_remaining != null
      ? quota.data.queries_limit - quota.data.queries_remaining
      : 0
  const quotaLimit = quota.data?.queries_limit ?? 0

  return (
    <div className="space-y-6">

      {/* ── Header ──────────────────────────────────────────────────── */}
      <ScrollReveal>
        <h1 className="text-2xl font-medium">Investigations</h1>
      </ScrollReveal>

      {/* ── Ask a question ──────────────────────────────────────────── */}
      <ScrollReveal delay={0.04}>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Ask a business question</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">

            {/* Data source picker */}
            <div className="relative">
              <Database className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <select
                className="w-full rounded-md border border-input bg-background py-2 pl-8 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">Select a data source</option>
                {(ds.data ?? []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name}
                  </option>
                ))}
              </select>
            </div>

            {/* Question textarea */}
            <Textarea
              placeholder="Why did profitability decline?   ·   Top 10 customers by revenue"
              value={question}
              rows={3}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && question.trim() && !create.isPending) {
                  submit()
                }
              }}
            />

            {/* Quota + submit */}
            <div className="space-y-2">
              {quotaLimit > 0 && (
                <QuotaBar used={quotaUsed} limit={quotaLimit} />
              )}
              <div className="flex items-center justify-between gap-3">
                <span className="text-[11px] text-muted-foreground">
                  ⌘ + Enter to submit
                </span>
                <Button
                  onClick={submit}
                  disabled={create.isPending || !question.trim()}
                >
                  {create.isPending ? "Starting…" : "Investigate"}
                </Button>
              </div>
            </div>

            {/* Error */}
            <AnimatePresence>
              {create.isError && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    {(create.error as Error).message}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </CardContent>
        </Card>
      </ScrollReveal>

      {/* ── Investigations list ──────────────────────────────────────── */}
      <ScrollReveal delay={0.08}>
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">All investigations</CardTitle>
              {sorted.length > 0 && (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {sorted.length} total
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {inv.isLoading ? (
              <InvestigationsListSkeleton />
            ) : sorted.length === 0 ? (
              <EmptyState />
            ) : (
              sorted.map((i, idx) => (
                <InvestigationRow key={i.id} inv={i} index={idx} />
              ))
            )}
          </CardContent>
        </Card>
      </ScrollReveal>
    </div>
  )
}