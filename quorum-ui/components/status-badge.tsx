import type { ComponentType } from "react"
import { CheckCircle2, Clock, Loader2, XCircle, AlertTriangle, PauseCircle } from "lucide-react"
import { cn } from "@/lib/utils"

const STATUS_CONFIG: Record<
  string,
  { label: string; icon: ComponentType<{ className?: string }>; classes: string; dot: string }
> = {
  planning: {
    label: "Planning",
    icon: Clock,
    classes: "bg-indigo-50 text-indigo-700 border-indigo-200",
    dot: "bg-indigo-400",
  },
  running: {
    label: "Running",
    icon: Loader2,
    classes: "bg-blue-50 text-blue-700 border-blue-200",
    dot: "bg-blue-400",
  },
  completed: {
    label: "Completed",
    icon: CheckCircle2,
    classes: "bg-emerald-50 text-emerald-700 border-emerald-200",
    dot: "bg-emerald-400",
  },
  error: {
    label: "Failed",
    icon: XCircle,
    classes: "bg-rose-50 text-rose-700 border-rose-200",
    dot: "bg-rose-400",
  },
  escalated: {
    label: "Escalated",
    icon: AlertTriangle,
    classes: "bg-amber-50 text-amber-700 border-amber-200",
    dot: "bg-amber-400",
  },
  paused: {
    label: "Paused",
    icon: PauseCircle,
    classes: "bg-slate-50 text-slate-600 border-slate-200",
    dot: "bg-slate-400",
  },
}

export function StatusBadge({ s }: { s: string }) {
  const config = STATUS_CONFIG[s] ?? {
    label: s,
    icon: Clock,
    classes: "bg-muted text-muted-foreground border-border",
    dot: "bg-muted-foreground",
  }

  const Icon = config.icon
  const isRunning = s === "running"

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        config.classes,
      )}
    >
      <Icon
        className={cn("h-3 w-3", isRunning && "animate-spin")}
      />
      {config.label}
    </span>
  )
}
