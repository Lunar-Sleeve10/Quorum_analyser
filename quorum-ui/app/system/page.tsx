"use client"

import { useSystemStatus } from "@/hooks/use-api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  )
}

export default function SystemPage() {
  const s = useSystemStatus().data
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">System status</h1>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Runtime</CardTitle></CardHeader>
        <CardContent>
          <Row label="Database" value={s?.database.url_scheme ?? "—"} />
          <Row label="Band" value={s?.band_configured ? "configured" : "local mode"} />
          <Row label="LLM backend" value={s?.llm_backend ?? "—"} />
          <Row label="Semantic catalog" value={s?.semantic_catalog ? "loaded" : "—"} />
          <Row label="Credentials encrypted at rest" value={String(s?.credentials_encrypted_at_rest ?? false)} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Counts</CardTitle></CardHeader>
        <CardContent>
          <Row label="Investigations" value={s?.investigations ?? "—"} />
          <Row label="Rooms" value={s?.rooms ?? "—"} />
          <Row label="Findings" value={s?.findings ?? "—"} />
          <Row label="Data sources" value={s?.data_sources ?? "—"} />
          <Row label="Cached plans" value={s?.cached_plans ?? "—"} />
          <Row label="Dictionaries" value={s?.dictionaries ?? "—"} />
        </CardContent>
      </Card>
    </div>
  )
}
