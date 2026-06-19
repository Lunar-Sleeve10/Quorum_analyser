"use client"

import { use, useState } from "react"
import Link from "next/link"
import { useFollowup, useInvestigation, useRoom } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { TopologyBadge } from "@/components/topology-badge"
import { StatusBadge } from "@/components/status-badge"
import { ResultView } from "@/components/result-view"
import { CostPanel } from "@/components/cost-panel"
import { AgentRoom } from "@/components/agent-room"
import { ReportActions } from "@/components/report-actions"

export default function InvestigationDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const q = useInvestigation(id)
  const room = useRoom(id)
  const followup = useFollowup(id)
  const saved = useSession((s) => s.saved)
  const toggleSaved = useSession((s) => s.toggleSaved)
  const [text, setText] = useState("")
  const inv = q.data

  if (!inv) return <p className="text-sm text-muted-foreground">Loading…</p>

  const live = inv.status === "planning" || inv.status === "running"
  const canFollow = inv.followups_used < 2
  const messages = room.data?.messages ?? []

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <TopologyBadge t={inv.topology} />
          <StatusBadge s={inv.status} />
          {inv.confidence != null && <span className="text-xs text-muted-foreground">confidence {inv.confidence}</span>}
          <button onClick={() => toggleSaved(inv.id)} className="ml-auto text-sm">
            {saved.includes(inv.id) ? "★ Saved" : "☆ Save"}
          </button>
        </div>
        <h1 className="text-xl font-medium">{inv.normalized_question || inv.question}</h1>
        {inv.parent_investigation_id && (
          <Link href={`/investigations/${inv.parent_investigation_id}`} className="text-xs underline text-muted-foreground">
            Follow-up of a prior investigation
          </Link>
        )}
      </div>

      <CostPanel cost={inv.cost} topology={inv.topology} sql={inv.sql} />

      {inv.board_decision ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Board verdict</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="font-medium">{inv.board_decision.headline}</p>
            {inv.board_decision.primary_factor && <p>Primary driver: {inv.board_decision.primary_factor}</p>}
            {inv.board_decision.recommendation && <p className="text-muted-foreground">{inv.board_decision.recommendation}</p>}
            {inv.findings.length > 0 && (
              <div className="pt-2 space-y-1">
                {inv.findings.map((f, i) => <div key={i} className="text-muted-foreground">{f.label}: {f.evidence}</div>)}
              </div>
            )}
          </CardContent>
        </Card>
      ) : inv.authorized_result ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Result</CardTitle></CardHeader>
          <CardContent><ResultView result={inv.authorized_result} /></CardContent>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground">Working… the agents are collaborating.</p>
      )}

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Band room</CardTitle></CardHeader>
        <CardContent>
          <AgentRoom investigationId={inv.id} initial={messages} agents={room.data?.active_agents ?? []} done={!live}
/>
        </CardContent>
      </Card>

      {inv.governance.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Audit timeline</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            {inv.governance.map((g, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">{(g.ts ?? "").slice(11, 19)}</span>
                <span className="font-medium">{g.type}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Follow-up questions</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {inv.followups.length === 0 && <p className="text-sm text-muted-foreground">No follow-ups yet.</p>}
          {inv.followups.map((f) => (
            <Link key={f.id} href={`/investigations/${f.id}`} className="flex items-center gap-2 text-sm hover:underline">
              <StatusBadge s={f.status} />
              <span className="truncate">{f.question}</span>
            </Link>
          ))}
          <Separator />
          <div className="flex items-center gap-2">
            <Input
              placeholder={canFollow ? "Continue this investigation (reuses its context)" : "Follow-up limit reached"}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={!canFollow}
            />
            <Button
              disabled={!canFollow || followup.isPending || !text.trim()}
              onClick={async () => { await followup.mutateAsync(text.trim()); setText("") }}
            >
              {followup.isPending ? "Asking…" : "Ask"}
            </Button>
          </div>
          <span className="text-xs text-muted-foreground">Follow-ups used: {inv.followups_used} / 2</span>
        </CardContent>
      </Card>

      <ReportActions inv={inv} messages={messages} />
    </div>
  )
}
