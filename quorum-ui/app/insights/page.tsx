"use client"

import { useInvestigation } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { InvestigationPicker } from "@/components/investigation-picker"
import { ResultView } from "@/components/result-view"

export default function InsightsPage() {
  const id = useSession((s) => s.currentInvestigationId)
  const q = useInvestigation(id)
  const inv = q.data

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">Insights</h1>
      <InvestigationPicker />
      {!id && <p className="text-sm text-muted-foreground">Select an investigation.</p>}
      {inv && (
        <>
          <p className="text-sm text-muted-foreground">{inv.normalized_question || inv.question}</p>
          {inv.board_decision ? (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">Executive summary</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p className="font-medium">{inv.board_decision.headline}</p>
                {inv.board_decision.primary_factor && <p>Primary driver: {inv.board_decision.primary_factor}</p>}
                {inv.board_decision.recommendation && <p className="text-muted-foreground">{inv.board_decision.recommendation}</p>}
              </CardContent>
            </Card>
          ) : inv.authorized_result ? (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">Result</CardTitle></CardHeader>
              <CardContent><ResultView result={inv.authorized_result} /></CardContent>
            </Card>
          ) : (
            <p className="text-sm text-muted-foreground">No result yet.</p>
          )}
        </>
      )}
    </div>
  )
}
