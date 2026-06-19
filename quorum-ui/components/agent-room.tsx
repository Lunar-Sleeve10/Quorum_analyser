"use client"

import { useEffect, useRef, useState } from "react"
import { streamUrl } from "@/lib/api"
import type { RoomMessage } from "@/lib/types"
import { agentMeta, classify, displayName, EVENT_LABEL, EVENT_TONE } from "@/lib/agents"

function Avatar({ name, size = 7 }: { name: string; size?: number }) {
  const m = agentMeta(name)
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full text-[10px] font-medium text-white"
      style={{ background: m.color, height: `${size * 4}px`, width: `${size * 4}px` }}
    >
      {m.initials}
    </span>
  )
}

export function AgentRoom({
  investigationId, initial, agents, done, onEvent,
}: {
  investigationId: string
  initial: RoomMessage[]
  agents: string[]
  /** True once the investigation has reached a terminal state. When the run is
   *  done AND every message has been revealed, the "thinking" indicator stops. */
  done?: boolean
  onEvent?: (m: RoomMessage) => void
}) {
  const [messages, setMessages] = useState<RoomMessage[]>([])
  const [shown, setShown] = useState(0)
  const bottom = useRef<HTMLDivElement>(null)

  const merge = (incoming: RoomMessage[]) =>
    setMessages((prev) => {
      const map = new Map(prev.map((m) => [m.id, m]))
      for (const m of incoming) map.set(m.id, m)
      return Array.from(map.values()).sort((a, b) => String(a.ts ?? "").localeCompare(String(b.ts ?? "")))
    })

  // Reset when switching investigations.
  useEffect(() => { setMessages([]); setShown(0) }, [investigationId])
  useEffect(() => { if (initial.length) merge(initial) }, [investigationId, initial])

  // Live stream of new room messages.
  useEffect(() => {
    const es = new EventSource(streamUrl(investigationId))
    es.addEventListener("message", (e) => {
      try {
        const m = JSON.parse((e as MessageEvent).data) as RoomMessage
        onEvent?.(m)
        merge([m])
      } catch {}
    })
    es.addEventListener("status", () => es.close())
    es.onerror = () => es.close()
    return () => es.close()
  }, [investigationId])

  // Reveal one message at a time so the chain of thought is readable.
  useEffect(() => {
    if (shown >= messages.length) return
    const t = setTimeout(() => setShown((s) => Math.min(s + 1, messages.length)), 700)
    return () => clearTimeout(t)
  }, [shown, messages.length])

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }) }, [shown, messages.length])

  const roster = agents.length
    ? agents
    : ["Supervisor", "SQL Analyst", "Cost Sentinel", "Governance Guardian", "Decision Reporter"]

  const visible = messages.slice(0, shown)
  const revealing = shown < messages.length        // still playing out buffered messages
  // The ONLY conditions under which agents are "thinking":
  //   * we are still revealing buffered messages, OR
  //   * the run is not yet done and we've caught up (more is coming).
  const thinking = revealing || (!done && messages.length > 0)
  const allDone = !!done && !revealing

  const nextSender = messages[shown]?.sender
  const thinkingLabel = revealing && nextSender
    ? `${displayName(nextSender)} is thinking…`
    : "Agents are collaborating…"

  return (
    <div className="space-y-3">
      {/* Roster */}
      <div className="flex flex-wrap items-center gap-2">
        {roster.map((a) => (
          <span key={a} className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1 text-xs">
            <Avatar name={a} size={5} />{displayName(a)}
          </span>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {allDone ? `${messages.length} messages` : `${shown}/${messages.length || "…"}`}
        </span>
      </div>

      {/* Transcript */}
      <div className="max-h-[32rem] space-y-3 overflow-auto rounded-md border border-border bg-muted/20 p-3">
        {messages.length === 0 &&
          (done
            ? <p className="text-sm text-muted-foreground">No room transcript was recorded for this run.</p>
            : <p className="text-sm text-muted-foreground">Waiting for the agents to join the room…</p>)}

        {visible.map((m) => {
          const ev = classify(m.kind, m.summary)
          const meta = agentMeta(m.sender)
          return (
            <div key={m.id} className="flex gap-2 transition-opacity duration-300">
              <Avatar name={m.sender} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium">{displayName(m.sender)}</span>
                  {m.target && <span className="text-muted-foreground">→ {displayName(m.target)}</span>}
                  <span className={`uppercase tracking-wide ${EVENT_TONE[ev]}`}>{EVENT_LABEL[ev]}</span>
                  <span className="ml-auto font-mono text-muted-foreground">{(m.ts ?? "").slice(11, 19)}</span>
                </div>
                <div
                  className="mt-0.5 rounded-lg rounded-tl-sm border border-border bg-background px-3 py-1.5 text-sm"
                  style={{ borderLeft: `3px solid ${meta.color}` }}
                >
                  {m.summary}
                </div>
              </div>
            </div>
          )
        })}

        {/* Live "thinking" bubble — only while genuinely working. */}
        {thinking && (
          <div className="flex items-center gap-2 pl-9 text-xs text-muted-foreground">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
            </span>
            {thinkingLabel}
          </div>
        )}

        {/* Completed footer — replaces the perpetual spinner. */}
        {allDone && messages.length > 0 && (
          <div className="flex items-center gap-2 pt-1 text-xs text-emerald-600">
            <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            Discussion complete — the board reached a decision.
          </div>
        )}

        <div ref={bottom} />
      </div>
    </div>
  )
}
