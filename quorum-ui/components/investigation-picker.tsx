"use client"

import { useInvestigations } from "@/hooks/use-api"
import { useSession } from "@/store/session"

export function InvestigationPicker() {
  const inv = useInvestigations()
  const current = useSession((s) => s.currentInvestigationId)
  const setCurrent = useSession((s) => s.setCurrent)
  return (
    <select
      className="w-full max-w-xl rounded-md border border-input bg-background px-3 py-2 text-sm"
      value={current ?? ""}
      onChange={(e) => setCurrent(e.target.value || null)}
    >
      <option value="">Select an investigation</option>
      {(inv.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.question}</option>)}
    </select>
  )
}
