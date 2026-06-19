"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import type { ReactNode, ComponentType } from "react"
import { useDashboard, useDataSources, useInvestigations, useSystemStatus } from "@/hooks/use-api"
import { useSession } from "@/store/session"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LimitationsNotice } from "@/components/limitations-notice"
import { AnimatedBackground } from "@/components/motion/animated-background"
import { ScrollReveal } from "@/components/motion/scroll-reveal"
import { StatusBadge } from "@/components/status-badge"
import {
  Activity,
  ShieldCheck,
  AlertTriangle,
  Zap,
  ArrowRight,
  Database,
  Search,
  CheckCircle2,
  Circle,
  Star,
} from "lucide-react"
import { cn } from "@/lib/utils"

/* ── KPI card ─────────────────────────────────────────────────────────── */

function Kpi({
  label,
  value,
  description,
  icon: Icon,
  accent,
}: {
  label: string
  value: ReactNode
  description?: string
  icon: ComponentType<{ className?: string }>
  accent?: string
}) {
  return (
    <Card>
      <CardContent className="pt-4 pb-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-xs text-muted-foreground font-medium">{label}</div>
            <div className={cn("text-2xl font-semibold mt-1", accent)}>{value}</div>
            {description && (
              <div className="text-[10px] text-muted-foreground mt-1">{description}</div>
            )}
          </div>
          <div className={cn("rounded-lg p-2 bg-muted/50", accent)}>
            <Icon className="h-4 w-4 text-muted-foreground" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/* ── Investigation row ───────────────────────────────────────────────── */

function InvestigationRow({
  id,
  question,
  status,
  topology,
}: {
  id: string
  question: string
  status: string
  topology?: string
}) {
  return (
    <Link
      href={`/investigations/${id}`}
      className="group flex items-center gap-3 rounded-lg px-3 py-2.5 -mx-3 hover:bg-muted/50 transition-colors"
    >
      <StatusBadge s={status} />
      <span className="flex-1 truncate text-sm text-foreground group-hover:text-foreground/80">
        {question}
      </span>
      <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
    </Link>
  )
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export default function Dashboard() {
  const router = useRouter()
  const d = useDashboard()
  const s = useSystemStatus()
  const inv = useInvestigations()
  const ds = useDataSources()
  const setDataSource = useSession(x => x.setDataSource)
  const setCurrent = useSession(x => x.setCurrent)
  const saved = useSession(x => x.saved)

  const active = (inv.data ?? []).filter(
    i => i.status === "planning" || i.status === "running",
  )
  const demos = (ds.data ?? []).filter(x => x.is_sample)
  const savedItems = (inv.data ?? []).filter(i => saved.includes(i.id))

  const startDemo = (id: string) => {
    setDataSource(id)
    setCurrent(null)
    router.push("/investigations")
  }

  return (
    <div className="space-y-6 pb-12">

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-xl border border-border px-6 py-8">
        <AnimatedBackground />
        <ScrollReveal y={16}>
          <div className="relative z-10 space-y-2">
            <h1 className="text-2xl font-semibold">AI Analyst Workspace</h1>
            <p className="text-sm text-muted-foreground max-w-md">
              Governed multi-agent analytics. Every investigation goes through planning,
              governance review, and validation before delivering results.
            </p>
            <div className="flex gap-2 pt-2">
              <Button onClick={() => router.push("/investigations")} size="sm">
                Start investigation
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => router.push("/data-sources")}>
                Connect data
              </Button>
            </div>
          </div>
        </ScrollReveal>
      </div>

      {/* ── KPIs ──────────────────────────────────────────────────────── */}
      <ScrollReveal delay={0.05}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi
            label="Active investigations"
            value={d.data?.active_investigations ?? "—"}
            icon={Activity}
            description="Currently running"
          />
          <Kpi
            label="Review boards"
            value={d.data?.review_boards ?? "—"}
            icon={ShieldCheck}
            description="Governance sessions"
          />
          <Kpi
            label="Escalations"
            value={d.data?.escalations ?? "—"}
            icon={AlertTriangle}
            accent={d.data?.escalations && d.data.escalations > 0 ? "text-amber-600" : undefined}
            description="Requiring attention"
          />
          <Kpi
            label="Queries remaining"
            value={d.data?.queries_remaining ?? "—"}
            icon={Zap}
            description={`of ${d.data?.queries_remaining ?? "—"} total`}
          />
        </div>
      </ScrollReveal>

      {/* ── How it works ──────────────────────────────────────────────── */}
      <ScrollReveal delay={0.08}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">How it works</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-3 gap-4">
              {[
                {
                  step: "1",
                  title: "Connect or choose a database",
                  description: "Start from a demo database below, or connect your own on ",
                  link: { href: "/data-sources", label: "Data Sources" },
                },
                {
                  step: "2",
                  title: "Ask a business question",
                  description: "Head to ",
                  link: { href: "/investigations", label: "Investigations" },
                  suffix: " and type your question in plain language.",
                },
                {
                  step: "3",
                  title: "Watch the agents collaborate",
                  description:
                    "A team of AI specialists plans, reviews, queries, and validates results before delivering a governed report.",
                },
              ].map(item => (
                <div key={item.step} className="flex gap-3">
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                    {item.step}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-foreground">{item.title}</div>
                    <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                      {item.description}
                      {item.link && (
                        <Link href={item.link.href} className="underline hover:text-foreground">
                          {item.link.label}
                        </Link>
                      )}
                      {item.suffix}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </ScrollReveal>

      {/* ── Demo databases ────────────────────────────────────────────── */}
      <ScrollReveal delay={0.12}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Demo databases</CardTitle>
          </CardHeader>
          <CardContent>
            {demos.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-8 text-center">
                <Database className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
                <p className="text-sm font-medium text-muted-foreground">No demo databases available</p>
                <p className="text-xs text-muted-foreground/60 mt-1">
                  Add chinook.db or northwind.db to data/samples and restart the API.
                </p>
                <Link href="/data-sources">
                  <Button size="sm" variant="outline" className="mt-4">
                    Connect your own data
                  </Button>
                </Link>
              </div>
            ) : (
              <div className="flex flex-wrap gap-3">
                {demos.map(x => (
                  <div
                    key={x.id}
                    className="flex flex-col justify-between rounded-xl border border-border bg-muted/20 p-4 w-56 gap-3"
                  >
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <Database className="h-4 w-4 text-muted-foreground" />
                        <span className="font-semibold text-sm">{x.display_name}</span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Full schema · no restrictions
                      </div>
                    </div>
                    <Button size="sm" variant="outline" onClick={() => startDemo(x.id)}>
                      Explore
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </ScrollReveal>

      {/* ── Active + Recent ────────────────────────────────────────────── */}
      <ScrollReveal delay={0.16}>
        <div className="grid md:grid-cols-2 gap-3">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Active investigations</CardTitle>
            </CardHeader>
            <CardContent>
              {active.length === 0 ? (
                <div className="flex flex-col items-center py-6 text-center gap-2">
                  <Search className="h-7 w-7 text-muted-foreground/30" />
                  <p className="text-xs text-muted-foreground">No investigations running.</p>
                  <Link href="/investigations">
                    <Button size="sm" variant="ghost" className="text-xs h-7">
                      Start one →
                    </Button>
                  </Link>
                </div>
              ) : (
                <div className="space-y-0.5">
                  {active.map(i => (
                    <InvestigationRow
                      key={i.id}
                      id={i.id}
                      question={i.question}
                      status={i.status}
                      topology={i.topology}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Recent investigations</CardTitle>
            </CardHeader>
            <CardContent>
              {(d.data?.recent ?? []).length === 0 ? (
                <div className="flex flex-col items-center py-6 text-center gap-2">
                  <CheckCircle2 className="h-7 w-7 text-muted-foreground/30" />
                  <p className="text-xs text-muted-foreground">No recent activity.</p>
                </div>
              ) : (
                <div className="space-y-0.5">
                  {(d.data?.recent ?? []).slice(0, 6).map(r => (
                    <InvestigationRow
                      key={r.id}
                      id={r.id}
                      question={r.question}
                      status={r.status}
                      topology={r.topology}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </ScrollReveal>

      {/* ── Saved + System ────────────────────────────────────────────── */}
      <ScrollReveal delay={0.2}>
        <div className="grid md:grid-cols-2 gap-3">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Saved investigations</CardTitle>
            </CardHeader>
            <CardContent>
              {savedItems.length === 0 ? (
                <div className="flex flex-col items-center py-6 text-center gap-2">
                  <Star className="h-7 w-7 text-muted-foreground/30" />
                  <p className="text-xs text-muted-foreground">
                    Star an investigation to save it here.
                  </p>
                </div>
              ) : (
                <div className="space-y-0.5">
                  {savedItems.map(i => (
                    <InvestigationRow
                      key={i.id}
                      id={i.id}
                      question={i.question}
                      status={i.status}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">System status</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Band", value: s.data?.band_configured ? "Configured" : "Local mode" },
                  { label: "Database", value: s.data?.database.url_scheme ?? "—" },
                  { label: "LLM backend", value: s.data?.llm_backend ?? "—" },
                  { label: "Rooms", value: s.data?.rooms ?? "—" },
                ].map(item => (
                  <div key={item.label}>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
                      {item.label}
                    </div>
                    <div className="flex items-center gap-1.5 text-sm text-foreground">
                      <Circle
                        className={cn(
                          "h-2 w-2 fill-current",
                          item.value === "—"
                            ? "text-slate-300"
                            : "text-emerald-400",
                        )}
                      />
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </ScrollReveal>

      <ScrollReveal delay={0.24}>
        <LimitationsNotice />
      </ScrollReveal>
    </div>
  )
}
