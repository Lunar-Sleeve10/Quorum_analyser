"use client"

import { useState } from "react"
import { Check, Loader2, X, AlertTriangle } from "lucide-react"
import { motion } from "motion/react"
import { cn } from "@/lib/utils"
import type { InvestigationDetail } from "@/lib/types"

interface WorkflowStage {
  id: number
  label: string
  shortLabel: string
  description: string
  agent?: string
}

const STAGES: WorkflowStage[] = [
  {
    id: 0,
    label: "Question",
    shortLabel: "Q",
    description: "Business question received and queued for analysis.",
  },
  {
    id: 1,
    label: "Planning",
    shortLabel: "Plan",
    description: "The Planner decomposes your question into a structured multi-step analysis plan.",
    agent: "Planner",
  },
  {
    id: 2,
    label: "Governance",
    shortLabel: "Gov",
    description:
      "The Governance Guardian validates that the plan correctly covers all required business factors before any data is touched.",
    agent: "Governance Guardian",
  },
  {
    id: 3,
    label: "SQL Generation",
    shortLabel: "SQL",
    description:
      "The SQL Analyst translates the approved plan into one or more optimized database queries.",
    agent: "SQL Analyst",
  },
  {
    id: 4,
    label: "SQL Validation",
    shortLabel: "Val",
    description:
      "The Cost Sentinel validates query efficiency, estimated execution cost, and compliance with the approved plan.",
    agent: "Cost Sentinel",
  },
  {
    id: 5,
    label: "Data Review",
    shortLabel: "Rev",
    description:
      "The Reviewer verifies result quality, data integrity, and that findings align with the original question.",
    agent: "Reviewer",
  },
  {
    id: 6,
    label: "Reporting",
    shortLabel: "Rep",
    description:
      "The Decision Reporter compiles all validated findings into the final executive report.",
    agent: "Decision Reporter",
  },
  {
    id: 7,
    label: "Completed",
    shortLabel: "Done",
    description: "Analysis delivered and authorized for use.",
  },
]

function deriveCurrentStage(inv: InvestigationDetail): { stage: number; failed: boolean } {
  const { status, sql, board_decision, authorized_result, governance, findings } = inv

  if (status === "error") return { stage: -1, failed: true }
  if (status === "completed") return { stage: 7, failed: false }

  const govTypes = governance.map(g => (g.type ?? "").toLowerCase())

  if (board_decision || findings.length > 0) return { stage: 6, failed: false }
  if (authorized_result) return { stage: 5, failed: false }
  if (govTypes.some(t => t.includes("sentinel") || t.includes("cost") || t.includes("sqlval"))) {
    return { stage: 4, failed: false }
  }
  if (sql) return { stage: 3, failed: false }
  if (
    govTypes.some(
      t =>
        t.includes("guardian") ||
        t.includes("governance") ||
        t.includes("revision") ||
        t.includes("planguardian") ||
        t.includes("review"),
    )
  ) {
    return { stage: 2, failed: false }
  }

  return { stage: 1, failed: false }
}

export function WorkflowTimeline({ inv }: { inv: InvestigationDetail }) {
  const { stage: currentStage, failed } = deriveCurrentStage(inv)
  const [hovered, setHovered] = useState<number | null>(null)

  const getStageState = (id: number) => {
    if (failed) return id < currentStage ? "done" : id === currentStage ? "failed" : "pending"
    if (id < currentStage) return "done"
    if (id === currentStage) return "active"
    return "pending"
  }

  const hoveredStage = hovered !== null ? STAGES[hovered] : null

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">Execution Pipeline</div>
          <div className="text-xs text-muted-foreground mt-0.5">
            Shows the complete lifecycle of this investigation from planning through reporting.
            Hover any stage for details.
          </div>
        </div>
        {failed && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 border border-rose-200 px-2.5 py-1 text-xs font-medium text-rose-700 shrink-0">
            <AlertTriangle className="h-3 w-3" />
            Failed
          </span>
        )}
      </div>

      {/* Stage nodes — horizontally scrollable */}
      <div className="overflow-x-auto pb-1">
        <div className="flex items-start min-w-max">
          {STAGES.map((stage, i) => {
            const state = getStageState(stage.id)
            const isDone = state === "done"
            const isActive = state === "active"
            const isPending = state === "pending"
            const isFailed = state === "failed"
            const isHovered = hovered === i
            const connectorGreen = !failed && i < currentStage

            return (
              <div key={stage.id} className="flex items-center">
                <button
                  className="flex flex-col items-center gap-1.5 focus:outline-none"
                  style={{ width: 72 }}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(i)}
                  onBlur={() => setHovered(null)}
                  aria-label={`${stage.label}: ${stage.description}`}
                >
                  {/* Circle */}
                  <div
                    className={cn(
                      "relative flex h-7 w-7 items-center justify-center rounded-full border-2 transition-all duration-300",
                      isDone && "border-emerald-500 bg-emerald-500",
                      isActive && "border-indigo-500 bg-white dark:bg-indigo-950",
                      isPending &&
                        (isHovered
                          ? "border-muted-foreground/40 bg-muted/40"
                          : "border-border bg-background"),
                      isFailed && "border-rose-500 bg-rose-50",
                      isHovered && !isPending && "shadow-sm",
                    )}
                  >
                    {isDone && <Check className="h-3.5 w-3.5 text-white" strokeWidth={3} />}
                    {isActive && (
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }}
                      >
                        <Loader2 className="h-3.5 w-3.5 text-indigo-600" />
                      </motion.div>
                    )}
                    {isPending && (
                      <div className="h-2 w-2 rounded-full bg-muted-foreground/25" />
                    )}
                    {isFailed && (
                      <X className="h-3.5 w-3.5 text-rose-600" strokeWidth={3} />
                    )}

                    {/* Pulse ring for active stage */}
                    {isActive && (
                      <motion.div
                        className="absolute inset-0 rounded-full border-2 border-indigo-400"
                        animate={{ scale: [1, 1.8], opacity: [0.6, 0] }}
                        transition={{ repeat: Infinity, duration: 1.6, ease: "easeOut" }}
                      />
                    )}
                  </div>

                  {/* Label */}
                  <span
                    className={cn(
                      "text-[10px] text-center leading-tight font-medium w-full px-1",
                      isDone && "text-emerald-700",
                      isActive && "text-indigo-700 font-semibold",
                      isPending && "text-muted-foreground",
                      isFailed && "text-rose-700",
                    )}
                  >
                    {stage.shortLabel}
                  </span>
                </button>

                {/* Connector line */}
                {i < STAGES.length - 1 && (
                  <div
                    className={cn(
                      "h-0.5 w-6 flex-shrink-0 transition-colors duration-500",
                      connectorGreen ? "bg-emerald-400" : "bg-border",
                    )}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Stage detail — shown outside the scroll container to avoid clip */}
      <div className="min-h-[2.5rem]">
        {hoveredStage ? (
          <motion.div
            key={hoveredStage.id}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs"
          >
            <span className="font-semibold text-foreground">{hoveredStage.label}</span>
            {hoveredStage.agent && (
              <span className="text-muted-foreground"> · {hoveredStage.agent}</span>
            )}
            <p className="text-muted-foreground mt-0.5 leading-relaxed">
              {hoveredStage.description}
            </p>
          </motion.div>
        ) : (
          <p className="text-xs text-muted-foreground/50 px-1">
            Hover a stage to see what happens at that step.
          </p>
        )}
      </div>
    </div>
  )
}
