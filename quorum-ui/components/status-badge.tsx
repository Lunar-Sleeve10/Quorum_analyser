import { Badge } from "@/components/ui/badge"

export function StatusBadge({ s }: { s: string }) {
  const variant = s === "completed" ? "default" : s === "error" ? "destructive" : "outline"
  return <Badge variant={variant}>{s}</Badge>
}
