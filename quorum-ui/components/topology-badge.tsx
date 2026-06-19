import { GitBranch, Network } from "lucide-react"
import { cn } from "@/lib/utils"

const TOPOLOGY_CONFIG = {
  governed_chain: {
    label: "Governed Chain",
    sublabel: "Linear · sequential",
    icon: GitBranch,
    classes: "bg-violet-50 text-violet-700 border-violet-200",
  },
  investigation_board: {
    label: "Investigation Board",
    sublabel: "Parallel · diagnostic",
    icon: Network,
    classes: "bg-sky-50 text-sky-700 border-sky-200",
  },
}

export function TopologyBadge({ t }: { t: string }) {
  const config =
    TOPOLOGY_CONFIG[t as keyof typeof TOPOLOGY_CONFIG] ?? {
      label: t,
      sublabel: null,
      icon: GitBranch,
      classes: "bg-muted text-muted-foreground border-border",
    }

  const Icon = config.icon

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        config.classes,
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  )
}
