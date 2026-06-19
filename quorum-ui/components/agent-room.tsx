"use client"

import { useEffect, useRef, useState } from "react"
import { motion, AnimatePresence } from "motion/react"
import { ChevronDown, ChevronUp, RefreshCw, Users, MessageSquare } from "lucide-react"
import { streamUrl } from "@/lib/api"
import type { RoomMessage } from "@/lib/types"
import { agentMeta, classify, displayName, EVENT_LABEL, EVENT_TONE } from "@/lib/agents"
import { cn } from "@/lib/utils"

/* ── Agent meta ─────────────────────────────────────────────────────── */

const AGENT_DESCRIPTIONS: Record<string, string> = {
  Planner: "Decomposes your business question into a structured, multi-step analysis plan.",
  Supervisor: "Coordinates the investigation workflow and delegates tasks to specialist agents.",
  "SQL Analyst": "Translates the approved plan into optimized SQL queries for execution.",
  "Cost Sentinel": "Validates SQL efficiency, estimated cost, and compliance with the approved plan.",
  "Governance Guardian":
    "Reviews whether the plan correctly covers all required business factors before any data is touched.",
  "Decision Reporter":
    "Compiles all validated findings into the final executive report.",
  Reviewer:
    "Verifies result quality, data integrity, and that findings match the original question.",
  Investigator: "Conducts deep analysis of specific aspects of the business question.",
  Adjudicator: "Resolves governance conflicts and makes final escalation decisions.",
}

type AgentStatus =
  | "pending" | "online" | "active" | "reviewing"
  | "revision" | "approved" | "completed" | "error"

const STATUS_STYLES: Record<
  AgentStatus,
  { dot: string; text: string; bg: string; border: string; label: string }
> = {
  pending:   { dot: "bg-slate-300",                  text: "text-slate-500",   bg: "",                    border: "border-border",       label: "Pending"             },
  online:    { dot: "bg-emerald-400",                text: "text-emerald-700", bg: "bg-emerald-50/40",    border: "border-emerald-200",  label: "Online"              },
  active:    { dot: "bg-blue-400 animate-pulse",     text: "text-blue-700",    bg: "bg-blue-50/40",       border: "border-blue-200",     label: "Active"              },
  reviewing: { dot: "bg-indigo-400 animate-pulse",   text: "text-indigo-700",  bg: "bg-indigo-50/40",     border: "border-indigo-200",   label: "Reviewing"           },
  revision:  { dot: "bg-amber-400",                  text: "text-amber-700",   bg: "bg-amber-50/40",      border: "border-amber-200",    label: "Revision Requested"  },
  approved:  { dot: "bg-emerald-400",                text: "text-emerald-700", bg: "bg-emerald-50/40",    border: "border-emerald-200",  label: "Approved"            },
  completed: { dot: "bg-emerald-400",                text: "text-emerald-600", bg: "",                    border: "border-border",       label: "Completed"           },
  error:     { dot: "bg-rose-400",                   text: "text-rose-700",    bg: "bg-rose-50/40",       border: "border-rose-200",     label: "Failed"              },
}

const PREFERRED_ORDER = [
  "Planner", "Supervisor", "Governance Guardian",
  "SQL Analyst", "Cost Sentinel", "Reviewer",
  "Decision Reporter", "Investigator", "Adjudicator",
]

function deriveAgentStatus(
  agentDisplayName: string,
  visibleMessages: RoomMessage[],
  done: boolean,
): { status: AgentStatus; lastMessage: RoomMessage | null; revisionCount: number } {
  const msgs = visibleMessages.filter(m => displayName(m.sender) === agentDisplayName)
  const revisionCount = msgs.filter(m => classify(m.kind, m.summary) === "challenge").length
  const last = msgs[msgs.length - 1] ?? null

  if (!last) return { status: "pending", lastMessage: null, revisionCount: 0 }
  if (done) return { status: "completed", lastMessage: last, revisionCount }

  const ev = classify(last.kind, last.summary)
  let status: AgentStatus
  if      (ev === "challenge")                          status = "revision"
  else if (ev === "approve" || ev === "adjudication")   status = "approved"
  else if (ev === "report"  || ev === "finding")        status = "completed"
  else if (ev === "review")                             status = "reviewing"
  else if (ev === "join"    || ev === "recruit")        status = "online"
  else                                                  status = "active"

  return { status, lastMessage: last, revisionCount }
}

/* ── Avatar ──────────────────────────────────────────────────────────── */

function Avatar({ name, size = 7 }: { name: string; size?: number }) {
  const m = agentMeta(name)
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-lg text-[10px] font-bold text-white"
      style={{ background: m.color, height: `${size * 4}px`, width: `${size * 4}px` }}
    >
      {m.initials}
    </span>
  )
}

/* ── Agent status card ───────────────────────────────────────────────── */

function AgentCard({
  name,
  visibleMessages,
  done,
}: {
  name: string
  visibleMessages: RoomMessage[]
  done: boolean
}) {
  const meta = agentMeta(name)
  const { status, lastMessage, revisionCount } = deriveAgentStatus(name, visibleMessages, done)
  const style = STATUS_STYLES[status]
  const description = AGENT_DESCRIPTIONS[name] ?? "Specialist AI agent in the investigation."
  const isPending = status === "pending"

  return (
    <div
      className={cn(
        "rounded-xl border p-3 transition-all duration-300 space-y-2.5",
        style.bg,
        style.border,
        isPending && "opacity-50",
      )}
    >
      {/* Header */}
      <div className="flex items-start gap-2.5">
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold text-white"
          style={{ background: meta.color }}
        >
          {meta.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold text-foreground">{name}</span>
            {revisionCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 border border-amber-200 px-1.5 text-[9px] font-semibold text-amber-700">
                <RefreshCw className="h-2 w-2" />
                {revisionCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
            <span className={cn("text-[10px] font-medium", style.text)}>{style.label}</span>
          </div>
        </div>
      </div>

      {/* Role description */}
      <p className="text-[10px] leading-relaxed text-muted-foreground">{description}</p>

      {/* Last decision */}
      {lastMessage && (
        <div className="rounded-md bg-background/60 border border-border/50 p-2">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Last decision
          </div>
          <p className="text-[10px] leading-relaxed text-foreground line-clamp-3">
            {lastMessage.summary}
          </p>
          {lastMessage.ts && (
            <div className="mt-1.5 text-[9px] text-muted-foreground/60 font-mono">
              {lastMessage.ts.slice(11, 19)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Main component ──────────────────────────────────────────────────── */

export function AgentRoom({
  investigationId,
  initial,
  agents,
  done,
  onEvent,
}: {
  investigationId: string
  initial: RoomMessage[]
  agents: string[]
  done?: boolean
  onEvent?: (m: RoomMessage) => void
}) {
  const [messages, setMessages] = useState<RoomMessage[]>([])
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set())
  const [showTranscript, setShowTranscript] = useState(true)
  const bottom = useRef<HTMLDivElement>(null)

  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  const messagesRef = useRef<RoomMessage[]>([])
  messagesRef.current = messages

  const merge = (incoming: RoomMessage[]) =>
    setMessages(prev => {
      const map = new Map(prev.map(m => [m.id, m]))
      let hasNew = false
      for (const m of incoming) {
        if (!map.has(m.id)) hasNew = true
        map.set(m.id, m)
      }
      if (!hasNew) return prev
      return Array.from(map.values()).sort((a, b) => {
        const tsA = a.ts ?? ""
        const tsB = b.ts ?? ""
        const cmp = tsA < tsB ? -1 : tsA > tsB ? 1 : 0
        return cmp !== 0 ? cmp : a.id.localeCompare(b.id)
      })
    })

  useEffect(() => { setMessages([]); setRevealedIds(new Set()) }, [investigationId])
  useEffect(() => { if (initial.length) merge(initial) }, [investigationId, initial])

  useEffect(() => {
    const es = new EventSource(streamUrl(investigationId))
    es.addEventListener("message", e => {
      try {
        const m = JSON.parse((e as MessageEvent).data) as RoomMessage
        onEventRef.current?.(m)
        merge([m])
      } catch {}
    })
    es.addEventListener("status", () => es.close())
    return () => es.close()
  }, [investigationId])

  useEffect(() => {
    const next = messagesRef.current.find(m => !revealedIds.has(m.id))
    if (!next) return
    const t = setTimeout(() => {
      setRevealedIds(prev => new Set([...prev, next.id]))
    }, 700)
    return () => clearTimeout(t)
  }, [revealedIds, messages.length])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" })
  }, [revealedIds, messages.length])

  const roster = agents.length
    ? agents
    : ["Supervisor", "SQL Analyst", "Cost Sentinel", "Governance Guardian", "Decision Reporter"]

  const visible = messages.filter(m => revealedIds.has(m.id))
  const revealing = revealedIds.size < messages.length
  const thinking = revealing || (!done && messages.length > 0)
  const allDone = !!done && !revealing

  const nextUnrevealed = messages.find(m => !revealedIds.has(m.id))
  const thinkingLabel = revealing && nextUnrevealed
    ? `${displayName(nextUnrevealed.sender)} is thinking…`
    : "Agents are collaborating…"

  // Determine agent display names for cards
  const rosterDisplayNames = roster.map(displayName).filter(n => n !== "Agent")
  const messageDisplayNames = messages.map(m => displayName(m.sender)).filter(n => n !== "Agent")
  const allDisplayNames = [...new Set([...rosterDisplayNames, ...messageDisplayNames])]
  const sortedNames = [
    ...PREFERRED_ORDER.filter(n => allDisplayNames.includes(n)),
    ...allDisplayNames.filter(n => !PREFERRED_ORDER.includes(n)),
  ]

  return (
    <div className="space-y-4">
      {/* Section intro */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Users className="h-3.5 w-3.5" />
            <span className="font-medium">Click to inspect agent decisions and revision history.</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={cn(
            "inline-flex h-2 w-2 rounded-full",
            thinking ? "bg-blue-400 animate-pulse" : allDone ? "bg-emerald-400" : "bg-slate-300",
          )} />
          {allDone
            ? `${messages.length} messages · complete`
            : thinking
            ? `${revealedIds.size} / ${messages.length || "…"}`
            : "Waiting…"}
        </div>
      </div>

      {/* Agent status cards */}
      {sortedNames.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
          {sortedNames.map(name => (
            <AgentCard
              key={name}
              name={name}
              visibleMessages={visible}
              done={allDone}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            Waiting for the agents to join the room…
          </p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            Agent cards will appear as specialists become active.
          </p>
        </div>
      )}

      {/* Transcript toggle */}
      <div className="rounded-xl border border-border overflow-hidden">
        <button
          onClick={() => setShowTranscript(v => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-xs hover:bg-muted/40 transition-colors"
        >
          <div className="flex items-center gap-2 font-medium text-foreground">
            <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
            Message Stream
            {thinking && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 border border-blue-200 px-2 py-0.5 text-[10px] font-medium text-blue-700">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                Live
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-muted-foreground">
            <span>{visible.length} messages</span>
            {showTranscript ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </div>
        </button>

        <AnimatePresence initial={false}>
          {showTranscript && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <div className="max-h-[32rem] overflow-auto border-t border-border bg-muted/10 p-3 space-y-2.5">
                {visible.length === 0 && (
                  done
                    ? <p className="text-xs text-muted-foreground py-4 text-center">No room transcript was recorded for this run.</p>
                    : <p className="text-xs text-muted-foreground py-4 text-center">Waiting for the agents to join the room…</p>
                )}

                {visible.map(m => {
                  const ev = classify(m.kind, m.summary)
                  const meta = agentMeta(m.sender)
                  return (
                    <motion.div
                      key={m.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, ease: "easeOut" }}
                      className="flex gap-2.5"
                    >
                      <Avatar name={m.sender} size={7} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5 text-[10px] mb-1">
                          <span className="font-semibold text-foreground">{displayName(m.sender)}</span>
                          {m.target && (
                            <span className="text-muted-foreground">→ {displayName(m.target)}</span>
                          )}
                          <span className={cn("font-medium uppercase tracking-wide", EVENT_TONE[ev])}>
                            {EVENT_LABEL[ev]}
                          </span>
                          <span className="ml-auto font-mono text-muted-foreground">
                            {(m.ts ?? "").slice(11, 19)}
                          </span>
                        </div>
                        <div
                          className="rounded-lg rounded-tl-sm border border-border bg-background px-3 py-2 text-xs leading-relaxed"
                          style={{ borderLeft: `3px solid ${meta.color}` }}
                        >
                          {m.summary}
                        </div>
                      </div>
                    </motion.div>
                  )
                })}

                {/* Thinking indicator */}
                {thinking && (
                  <div className="flex items-center gap-2 pl-9 text-[11px] text-muted-foreground pt-1">
                    <span className="flex gap-1">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
                    </span>
                    {thinkingLabel}
                  </div>
                )}

                {/* Completed footer */}
                {allDone && messages.length > 0 && (
                  <div className="flex items-center gap-2 pt-1 text-[11px] text-emerald-600 border-t border-border mt-2">
                    <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                    Discussion complete — the board reached a decision.
                  </div>
                )}

                <div ref={bottom} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
