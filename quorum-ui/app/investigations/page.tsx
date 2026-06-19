"use client"

import { useState } from "react"
import Link from "next/link"
import { useCreateInvestigation, useDataSources, useInvestigations, useQuota } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { TopologyBadge } from "@/components/topology-badge"
import { StatusBadge } from "@/components/status-badge"

export default function InvestigationsPage() {
  const inv = useInvestigations()
  const ds = useDataSources()
  const quota = useQuota()
  const create = useCreateInvestigation()
  const setCurrent = useSession((s) => s.setCurrent)
  const [question, setQuestion] = useState("")
  const [source, setSource] = useState("")

  const submit = async () => {
    if (!question.trim()) return
    const r = await create.mutateAsync({ question: question.trim(), dataSourceId: source || null })
    setCurrent(r.id)
    setQuestion("")
  }

  const top = (inv.data ?? []).filter((i) => !i.parent_investigation_id)

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">Investigations</h1>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Ask a business question</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">Select a data source</option>
            {(ds.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.display_name}</option>)}
          </select>
          <Textarea
            placeholder="Why did profitability decline?   ·   top 10 customers by revenue"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Queries remaining: {quota.data?.queries_remaining ?? "—"} / {quota.data?.queries_limit ?? "—"}
            </span>
            <Button onClick={submit} disabled={create.isPending || !question.trim()}>
              {create.isPending ? "Asking…" : "Ask"}
            </Button>
          </div>
          {create.isError && <p className="text-sm text-destructive">{(create.error as Error).message}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">All investigations</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {top.length === 0 && <p className="text-sm text-muted-foreground">No investigations yet.</p>}
          {top.map((i) => (
            <Link key={i.id} href={`/investigations/${i.id}`} className="flex items-center gap-2 text-sm hover:underline">
              <TopologyBadge t={i.topology} />
              <StatusBadge s={i.status} />
              <span className="truncate">{i.question}</span>
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
