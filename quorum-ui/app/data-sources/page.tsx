"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { useConnectExternal, useDataSources, useSchema, useUploadDataSource, useDeleteDataSource } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import type { DataSource } from "@/lib/types"

function SourceSchema({ id }: { id: string }) {
  const [open, setOpen] = useState(false)
  const schema = useSchema(id, open)
  return (
    <div className="space-y-1">
      <Button variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>{open ? "Hide schema" : "Discover schema"}</Button>
      {open && schema.isLoading && <p className="text-sm text-muted-foreground">Reading schema…</p>}
      {open && schema.data && schema.data.tables.map((t) => (
        <div key={t.name} className="text-sm"><span className="font-medium">{t.name}</span> <span className="text-muted-foreground">({t.columns.length} cols)</span></div>
      ))}
    </div>
  )
}

const FIELDS: Record<string, [string, string, boolean][]> = {
  postgres: [["host", "Host", false], ["port", "Port", false], ["dbname", "Database", false], ["user", "User", false], ["password", "Password", true]],
  mysql: [["host", "Host", false], ["port", "Port", false], ["dbname", "Database", false], ["user", "User", false], ["password", "Password", true]],
  bigquery: [["project", "GCP project", false], ["dataset", "Dataset", false]],
}

function ConnectForm() {
  const connect = useConnectExternal()
  const [kind, setKind] = useState("postgres")
  const [name, setName] = useState("")
  const [vals, setVals] = useState<Record<string, string>>({})
  const set = (k: string, v: string) => setVals((p) => ({ ...p, [k]: v }))
  const submit = async () => {
    const secret = kind === "bigquery" ? {} : { user: vals.user, password: vals.password }
    const meta = kind === "bigquery"
      ? { project: vals.project, dataset: vals.dataset }
      : { host: vals.host, port: vals.port, dbname: vals.dbname }
    await connect.mutateAsync({ kind, displayName: name || kind, connectionMeta: meta, credentials: secret })
    setVals({}); setName("")
  }
  return (
    <div className="space-y-3">
      <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="postgres">PostgreSQL</option>
        <option value="mysql">MySQL</option>
        <option value="bigquery">BigQuery</option>
      </select>
      <Input placeholder="Display name" value={name} onChange={(e) => setName(e.target.value)} />
      {FIELDS[kind].map(([k, label, secret]) => (
        <Input key={k} placeholder={label} type={secret ? "password" : "text"} value={vals[k] ?? ""} onChange={(e) => set(k, e.target.value)} />
      ))}
      <p className="text-xs text-muted-foreground">Credentials are encrypted before storage and persist until you change the data source.</p>
      <Button onClick={submit} disabled={connect.isPending || !name.trim()}>{connect.isPending ? "Connecting…" : "Connect"}</Button>
      {connect.isSuccess && <p className="text-sm text-emerald-600">Connected. Credentials encrypted.</p>}
    </div>
  )
}

function UploadForm() {
  const upload = useUploadDataSource()
  const [file, setFile] = useState<File | null>(null)
  return (
    <div className="space-y-3">
      <input type="file" accept=".db,.sqlite,.sqlite3,.csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
      <p className="text-xs text-muted-foreground">Uploaded databases are limited to the first 5 tables and 5 columns per table.</p>
      <Button onClick={() => file && upload.mutate(file)} disabled={!file || upload.isPending}>{upload.isPending ? "Uploading…" : "Upload"}</Button>
    </div>
  )
}

export default function DataSourcesPage() {
  const router = useRouter()
  const ds = useDataSources()
  const del = useDeleteDataSource()
  const setDataSource = useSession((s) => s.setDataSource)
  const setCurrent = useSession((s) => s.setCurrent)
  const sources: DataSource[] = ds.data ?? []
  const demos = sources.filter((s) => s.is_sample)
  const mine = sources.filter((s) => !s.is_sample)
  const explore = (id: string) => { setDataSource(id); setCurrent(null); router.push("/investigations") }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-medium">Data sources</h1>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Demo databases</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          {demos.length === 0 && <p className="text-sm text-muted-foreground">Add chinook.db / northwind.db to data/samples and restart the API.</p>}
          {demos.map((d) => (
            <div key={d.id} className="rounded-md border border-border p-4 w-56">
              <div className="font-medium">{d.display_name}</div>
              <div className="text-xs text-muted-foreground mb-3">Full schema · no restrictions</div>
              <Button size="sm" onClick={() => explore(d.id)}>Explore</Button>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Connect a database</CardTitle></CardHeader>
          <CardContent><ConnectForm /></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Upload a file</CardTitle></CardHeader>
          <CardContent><UploadForm /></CardContent>
        </Card>
      </div>

      <Card>
  <CardHeader className="pb-2">
    <CardTitle className="text-base">Your databases</CardTitle>
  </CardHeader>

  <CardContent className="space-y-4">
    {mine.length === 0 && (
      <p className="text-sm text-muted-foreground">
        No connected or uploaded databases yet.
      </p>
    )}

    {mine.map((d) => (
      <div
        key={d.id}
        className="rounded-md border border-border p-3 space-y-2"
      >
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">{d.display_name}</span>

          <Badge variant="secondary">{d.kind}</Badge>

          {d.has_credentials && (
            <Badge variant="outline">
              credentials saved
            </Badge>
          )}

          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => explore(d.id)}
            >
              Use
            </Button>

            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (
                  confirm(
                    `Delete "${d.display_name}"? This cannot be undone.`
                  )
                ) {
                  del.mutate(d.id)
                }
              }}
            >
              Delete
            </Button>
          </div>
        </div>

        <SourceSchema id={d.id} />
      </div>
    ))}
  </CardContent>
</Card>

    
    </div>
  )
}
