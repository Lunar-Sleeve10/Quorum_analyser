"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import type { ReactNode } from "react"
import { useDashboard, useDataSources, useInvestigations, useSystemStatus } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LimitationsNotice } from "@/components/limitations-notice"

function Kpi({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-1"><CardTitle className="text-xs font-normal text-muted-foreground">{label}</CardTitle></CardHeader>
      <CardContent className="text-2xl font-medium">{value}</CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const router = useRouter()
  const d = useDashboard()
  const s = useSystemStatus()
  const inv = useInvestigations()
  const ds = useDataSources()
  const setDataSource = useSession((x) => x.setDataSource)
  const setCurrent = useSession((x) => x.setCurrent)
  const saved = useSession((x) => x.saved)

  const active = (inv.data ?? []).filter((i) => i.status === "planning" || i.status === "running")
  const demos = (ds.data ?? []).filter((x) => x.is_sample)
  const savedItems = (inv.data ?? []).filter((i) => saved.includes(i.id))

  const startDemo = (id: string) => { setDataSource(id); setCurrent(null); router.push("/investigations") }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-medium">Control tower</h1>
        <p className="text-sm text-muted-foreground">Governed multi-agent analytics over Band.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Active investigations" value={d.data?.active_investigations ?? "—"} />
        <Kpi label="Review boards" value={d.data?.review_boards ?? "—"} />
        <Kpi label="Escalations" value={d.data?.escalations ?? "—"} />
        <Kpi label="Queries remaining" value={d.data?.queries_remaining ?? "—"} />
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Quick start</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-1">
          <p>1. Start from a demo database below, or connect your own on <Link href="/data-sources" className="underline">Data Sources</Link>.</p>
          <p>2. Ask a question on <Link href="/investigations" className="underline">Investigations</Link>.</p>
          <p>3. Watch the agents collaborate inside the investigation, then export a report.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Demo databases</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          {demos.length === 0 && <p className="text-sm text-muted-foreground">Add chinook.db or northwind.db to data/samples and restart the API.</p>}
          {demos.map((x) => (
            <div key={x.id} className="rounded-md border border-border p-4 w-56">
              <div className="font-medium">{x.display_name}</div>
              <div className="text-xs text-muted-foreground mb-3">Full schema · no restrictions</div>
              <Button size="sm" onClick={() => startDemo(x.id)}>Explore</Button>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Active investigations</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {active.length === 0 && <p className="text-sm text-muted-foreground">None running.</p>}
            {active.map((i) => (
              <Link key={i.id} href={`/investigations/${i.id}`} className="flex items-center gap-2 text-sm hover:underline">
                <Badge variant="secondary">{i.topology === "investigation_board" ? "board" : "chain"}</Badge>
                <span className="truncate">{i.question}</span>
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Recent investigations</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {(d.data?.recent ?? []).length === 0 && <p className="text-sm text-muted-foreground">No recent activity.</p>}
            {(d.data?.recent ?? []).slice(0, 6).map((r) => (
              <Link key={r.id} href={`/investigations/${r.id}`} className="flex items-center justify-between gap-2 text-sm hover:underline">
                <span className="truncate">{r.question}</span>
                <Badge variant="outline">{r.status}</Badge>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Saved investigations</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {savedItems.length === 0 && <p className="text-sm text-muted-foreground">Star an investigation to save it.</p>}
            {savedItems.map((i) => (
              <Link key={i.id} href={`/investigations/${i.id}`} className="block text-sm hover:underline truncate">{i.question}</Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">System status</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-sm">
            <div><div className="text-muted-foreground">Band</div><div>{s.data?.band_configured ? "configured" : "local mode"}</div></div>
            <div><div className="text-muted-foreground">Database</div><div>{s.data?.database.url_scheme ?? "—"}</div></div>
            <div><div className="text-muted-foreground">LLM backend</div><div>{s.data?.llm_backend ?? "—"}</div></div>
            <div><div className="text-muted-foreground">Rooms</div><div>{s.data?.rooms ?? "—"}</div></div>
          </CardContent>
        </Card>
      </div>

      <LimitationsNotice />
    </div>
  )
}
