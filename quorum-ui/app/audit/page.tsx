"use client"

import { useInvestigation, useRoom } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { InvestigationPicker } from "@/components/investigation-picker"

export default function AuditPage() {
  const id = useSession((s) => s.currentInvestigationId)
  const inv = useInvestigation(id)
  const room = useRoom(id)

  const download = () => {
    const blob = new Blob([JSON.stringify({ investigation: inv.data, room: room.data }, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `audit_${id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">Audit trail</h1>
      <InvestigationPicker />
      {!id && <p className="text-sm text-muted-foreground">Select an investigation.</p>}
      {id && (
        <>
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">Transcript</CardTitle></CardHeader>
            <CardContent className="space-y-1 max-h-96 overflow-auto">
              {(room.data?.messages ?? []).map((m) => (
                <div key={m.id} className="text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{(m.ts ?? "").slice(11, 19)} </span>
                  <span className="font-medium">{m.sender}</span>
                  <span className="text-muted-foreground"> — {m.summary}</span>
                </div>
              ))}
              {(room.data?.messages ?? []).length === 0 && <p className="text-sm text-muted-foreground">No transcript.</p>}
            </CardContent>
          </Card>
          <Button variant="outline" onClick={download} disabled={!inv.data}>Download audit record (JSON)</Button>
        </>
      )}
    </div>
  )
}
