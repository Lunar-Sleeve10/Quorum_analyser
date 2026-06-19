import { Badge } from "@/components/ui/badge"

export function TopologyBadge({ t }: { t: string }) {
  return <Badge variant="secondary">{t === "investigation_board" ? "Investigation board" : "Governed chain"}</Badge>
}
