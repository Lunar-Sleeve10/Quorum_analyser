"use client"

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Funnel,
  FunnelChart, LabelList, Legend, Line, LineChart, Pie, PieChart, PolarAngleAxis,
  PolarGrid, PolarRadiusAxis, Radar, RadarChart, RadialBar, RadialBarChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, Treemap, XAxis, YAxis, ZAxis,
} from "recharts"
import type { VizSpec } from "@/lib/viz"
import type { TooltipContentProps } from "recharts"

/* ------------------------------------------------------------------ *
 * Cell access + formatting helpers (shared by viz.ts and result-view) *
 * Rows may arrive as arrays (rows[i][j]) or as objects keyed by column.*
 * ------------------------------------------------------------------ */

export function cell(row: unknown, columns: string[], j: number): unknown {
  if (Array.isArray(row)) return row[j]
  if (row && typeof row === "object") return (row as Record<string, unknown>)[columns[j]]
  return undefined
}

export function toFinite(v: unknown): number {
  if (typeof v === "number") return Number.isFinite(v) ? v : 0
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

export function toLabel(v: unknown): string {
  if (v === null || v === undefined) return ""
  return String(v)
}

const PALETTE = ["#6366f1", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#22c55e", "#3b82f6", "#ec4899", "#06b6d4", "#eab308"]
const TICK = { fontSize: 11 }

function fmt(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ""
  return Math.abs(n) >= 1000
    ? new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n)
    : String(Math.round(n * 100) / 100)
}

type TipProps = {
  active?: boolean
  label?: unknown
  payload?: readonly {
    name?: string
    value?: unknown
    color?: string
  }[]
} 
function ChartTooltip({ active, payload, label }: TooltipContentProps<any, any>) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs shadow-sm">
      {label !== undefined && label !== "" && <div className="mb-0.5 font-medium">{String(label)}</div>}
      {payload.map((p, i) => {
        const n = Number(p?.value)
        return (
          <div key={i} className="flex items-center gap-1.5 text-muted-foreground">
            {p?.color && <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />}
            <span>{p?.name ?? "value"}:</span>
            <span className="font-medium text-foreground">{Number.isFinite(n) ? fmt(n) : "—"}</span>
          </div>
        )
      })}
    </div>
  )
}

function render(spec: VizSpec) {
  const { type, category, metrics, data, sizeKey } = spec
  const grid = <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
  const xt = { tick: TICK, tickLine: false, axisLine: false } as const

  if (type === "pie" || type === "donut") {
    return (
      <PieChart>
        <Pie
          data={data} dataKey={metrics[0]} nameKey={category}
          outerRadius={110} innerRadius={type === "donut" ? 62 : 0} paddingAngle={2}
          label={(e: { name?: string; percent?: number }) => `${e.name ?? ""} ${((e.percent ?? 0) * 100).toFixed(0)}%`}
          labelLine={false}
        >
          {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
        </Pie>
        <Tooltip content={ChartTooltip} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    )
  }

  if (type === "scatter" || type === "bubble") {
    return (
      <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        {grid}
        <XAxis type="number" dataKey={category} name={category} {...xt} tickFormatter={fmt} />
        <YAxis type="number" dataKey={metrics[0]} name={metrics[0]} {...xt} width={52} tickFormatter={fmt} />
        {type === "bubble" && sizeKey && <ZAxis type="number" dataKey={sizeKey} range={[60, 600]} name={sizeKey} />}
        <Tooltip content={ChartTooltip} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter data={data} fill={PALETTE[0]} fillOpacity={0.7} />
      </ScatterChart>
    )
  }

  if (type === "line" || type === "multiLine") {
    return (
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        {grid}
        <XAxis dataKey={category} {...xt} interval="preserveStartEnd" />
        <YAxis {...xt} width={52} tickFormatter={fmt} />
        <Tooltip content={ChartTooltip} />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Line key={m} type="monotone" dataKey={m} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        ))}
      </LineChart>
    )
  }

  if (type === "area" || type === "stackedArea") {
    return (
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        {grid}
        <XAxis dataKey={category} {...xt} interval="preserveStartEnd" />
        <YAxis {...xt} width={52} tickFormatter={fmt} />
        <Tooltip content={ChartTooltip} />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Area
            key={m} type="monotone" dataKey={m}
            stackId={type === "stackedArea" ? "1" : undefined}
            stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]}
            fillOpacity={0.18} strokeWidth={2}
          />
        ))}
      </AreaChart>
    )
  }

  if (type === "radar") {
    return (
      <RadarChart data={data} outerRadius={110}>
        <PolarGrid opacity={0.4} />
        <PolarAngleAxis dataKey={category} tick={TICK} />
        <PolarRadiusAxis tick={TICK} tickFormatter={fmt} />
        <Tooltip content={ChartTooltip} />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Radar key={m} name={m} dataKey={m} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.22} />
        ))}
      </RadarChart>
    )
  }

  if (type === "radialBar") {
    return (
      <RadialBarChart data={data} innerRadius="25%" outerRadius="100%" startAngle={90} endAngle={-270}>
        <RadialBar background dataKey={metrics[0]}>
          {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
        </RadialBar>
        <Legend iconSize={10} layout="vertical" verticalAlign="middle" align="right" wrapperStyle={{ fontSize: 12 }} />
        <Tooltip content={ChartTooltip} />
      </RadialBarChart>
    )
  }

  if (type === "treemap") {
    const tm = data.map((d, i) => ({ name: String(d[category]), size: Number(d[metrics[0]]) || 0, fill: PALETTE[i % PALETTE.length] }))
    return (
      <Treemap data={tm} dataKey="size" nameKey="name" stroke="#fff" aspectRatio={4 / 3}>
        <Tooltip content={ChartTooltip} />
      </Treemap>
    )
  }

  if (type === "funnel") {
    const fn = data.map((d, i) => ({ name: String(d[category]), value: Number(d[metrics[0]]) || 0, fill: PALETTE[i % PALETTE.length] }))
    return (
      <FunnelChart>
        <Tooltip content={ChartTooltip} />
        <Funnel dataKey="value" data={fn} isAnimationActive>
          <LabelList position="right" fill="#475569" stroke="none" dataKey="name" fontSize={11} />
        </Funnel>
      </FunnelChart>
    )
  }

  if (type === "composed") {
    return (
      <ComposedChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        {grid}
        <XAxis dataKey={category} {...xt} interval="preserveStartEnd" />
        <YAxis yAxisId="l" {...xt} width={52} tickFormatter={fmt} />
        <YAxis yAxisId="r" orientation="right" {...xt} width={52} tickFormatter={fmt} />
        <Tooltip content={ChartTooltip} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar yAxisId="l" dataKey={metrics[0]} fill={PALETTE[0]} radius={[4, 4, 0, 0]} maxBarSize={48} />
        {metrics[1] && <Line yAxisId="r" type="monotone" dataKey={metrics[1]} stroke={PALETTE[2]} strokeWidth={2} dot={false} />}
      </ComposedChart>
    )
  }

  if (type === "hbar") {
    return (
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        {grid}
        <XAxis type="number" {...xt} tickFormatter={fmt} />
        <YAxis type="category" dataKey={category} {...xt} width={140} />
        <Tooltip content={ChartTooltip} cursor={{ fillOpacity: 0.06 }} />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Bar key={m} dataKey={m} fill={PALETTE[i % PALETTE.length]} radius={[0, 4, 4, 0]} maxBarSize={26} />
        ))}
      </BarChart>
    )
  }

  // bar | groupedBar | stackedBar (default)
  const stack = type === "stackedBar"
  return (
    <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
      {grid}
      <XAxis dataKey={category} {...xt} interval="preserveStartEnd" />
      <YAxis {...xt} width={52} tickFormatter={fmt} />
      <Tooltip content={ChartTooltip} cursor={{ fillOpacity: 0.06 }} />
      {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
      {metrics.map((m, i) => (
        <Bar key={m} dataKey={m} stackId={stack ? "1" : undefined} fill={PALETTE[i % PALETTE.length]} radius={stack ? 0 : [4, 4, 0, 0]} maxBarSize={48} />
      ))}
    </BarChart>
  )
}

export function Chart({ spec }: { spec: VizSpec }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="mb-0.5 text-sm font-medium">{spec.title}</div>
      {spec.subtitle && <div className="mb-3 text-xs text-muted-foreground">{spec.subtitle}</div>}
      <ResponsiveContainer width="100%" height={300}>
        {render(spec)}
      </ResponsiveContainer>
    </div>
  )
}
