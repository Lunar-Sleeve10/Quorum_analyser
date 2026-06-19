import { cell, toFinite, toLabel } from "@/lib/charts"

export type VizType =
  | "bar" | "hbar" | "groupedBar" | "stackedBar"
  | "line" | "multiLine" | "area" | "stackedArea"
  | "pie" | "donut" | "scatter" | "bubble"
  | "radar" | "radialBar" | "composed" | "treemap" | "funnel"

export interface VizSpec {
  type: VizType
  title: string
  subtitle?: string
  category: string
  metrics: string[]
  sizeKey?: string
  data: Record<string, number | string>[]
}

export interface Kpi { label: string; value: string; hint?: string }
export interface Insight { text: string; kind?: "up" | "down" | "info" | "warn" }
export interface Analysis {
  single: string | null
  kpis: Kpi[]
  charts: VizSpec[]
  insights: Insight[]
}

const TIME_RE = /(date|month|year|time|day|week|quarter|period|created|order|_at$|^yr$)/i
const ID_RE = /^id$|.id$|guid|uuid/i
const STAGE_RE = /(stage|step|status|phase|funnel|state)/i
const isNum = (v: unknown) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v))

const compact = (n: number) =>
  Math.abs(n) >= 1000
    ? new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n)
    : String(Math.round(n * 100) / 100)
const pct = (n: number) => `${(n * 100).toFixed(n * 100 >= 10 ? 0 : 1)}%`

function temporal(col: string, columns: string[], rows: unknown[], idx: number) {
  if (TIME_RE.test(col)) return true
  return rows.slice(0, 6).some((r) => /^\d{4}([-/]\d{1,2})?/.test(toLabel(cell(r, columns, idx))))
}

function pearson(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length)
  if (n < 3) return 0
  const ma = a.reduce((s, x) => s + x, 0) / n
  const mb = b.reduce((s, x) => s + x, 0) / n
  let num = 0, da = 0, db = 0
  for (let i = 0; i < n; i++) {
    const xa = a[i] - ma, xb = b[i] - mb
    num += xa * xb; da += xa * xa; db += xb * xb
  }
  const den = Math.sqrt(da * db)
  return den === 0 ? 0 : num / den
}

export function analyze(columns: string[], rows: unknown[]): Analysis {
  // Single scalar answer.
  if (columns.length === 1 && rows.length === 1) {
    return { single: toLabel(cell(rows[0], columns, 0)) || "—", kpis: [], charts: [], insights: [] }
  }
  if (!columns.length || !rows.length) return { single: null, kpis: [], charts: [], insights: [] }

  const numericIdx = columns.map((_, j) => j).filter((j) => rows.every((r) => isNum(cell(r, columns, j))))
  const metricIdx = numericIdx.filter((j) => !ID_RE.test(columns[j]))
  const metrics = metricIdx.length ? metricIdx : numericIdx
  const textIdx = columns.map((_, j) => j).filter((j) => !metrics.includes(j))

  let catIdx = textIdx.find((j) => temporal(columns[j], columns, rows, j))
  if (catIdx === undefined) catIdx = textIdx.find((j) => rows.some((r) => !isNum(cell(r, columns, j))))
  if (catIdx === undefined) catIdx = textIdx[0] ?? (metrics.length > 1 ? metrics[0] : 0)

  const catCol = columns[catIdx]
  const metricCols = metrics.filter((j) => j !== catIdx).map((j) => columns[j])
  const isTime = temporal(catCol, columns, rows, catIdx)

  // Shape the data once for the charts.
  const data = rows.map((r) => {
    const o: Record<string, number | string> = { [catCol]: toLabel(cell(r, columns, catIdx)) || "—" }
    metrics.filter((j) => j !== catIdx).forEach((j) => { o[columns[j]] = toFinite(cell(r, columns, j)) })
    return o
  })

  const kpis: Kpi[] = [{ label: "Rows", value: String(rows.length) }]
  const insights: Insight[] = []
  const charts: VizSpec[] = []

  // -------- No usable measure: correlation / distribution of raw numerics ----
  if (metricCols.length === 0) {
    if (numericIdx.length >= 2) {
      const xa = rows.map((r) => toFinite(cell(r, columns, numericIdx[0])))
      const ya = rows.map((r) => toFinite(cell(r, columns, numericIdx[1])))
      const sd = rows.map((r) => ({
        [columns[numericIdx[0]]]: toFinite(cell(r, columns, numericIdx[0])),
        [columns[numericIdx[1]]]: toFinite(cell(r, columns, numericIdx[1])),
        ...(numericIdx[2] !== undefined ? { [columns[numericIdx[2]]]: toFinite(cell(r, columns, numericIdx[2])) } : {}),
      }))
      const r = pearson(xa, ya)
      charts.push({
        type: numericIdx[2] !== undefined ? "bubble" : "scatter",
        title: `${columns[numericIdx[1]]} vs ${columns[numericIdx[0]]}`,
        subtitle: numericIdx[2] !== undefined ? `bubble size = ${columns[numericIdx[2]]}` : "relationship between two measures",
        category: columns[numericIdx[0]], metrics: [columns[numericIdx[1]]],
        sizeKey: numericIdx[2] !== undefined ? columns[numericIdx[2]] : undefined,
        data: sd,
      })
      if (Math.abs(r) >= 0.4) {
        insights.push({
          text: `${columns[numericIdx[0]]} and ${columns[numericIdx[1]]} are ${r > 0 ? "positively" : "negatively"} correlated (r = ${r.toFixed(2)}).`,
          kind: r > 0 ? "up" : "down",
        })
      } else {
        insights.push({ text: `No strong linear relationship between ${columns[numericIdx[0]]} and ${columns[numericIdx[1]]} (r = ${r.toFixed(2)}).`, kind: "info" })
      }
    }
    return { single: null, kpis, charts, insights }
  }

  // -------- Primary measure stats + KPIs --------------------------------------
  const m0 = metricCols[0]
  const vals = data.map((d) => Number(d[m0]) || 0)
  const total = vals.reduce((s, x) => s + x, 0)
  const avg = total / Math.max(1, vals.length)
  const sorted = [...data].sort((a, b) => Number(b[m0]) - Number(a[m0]))
  const top = sorted[0]
  const bottom = sorted[sorted.length - 1]
  const maxV = Number(top?.[m0]) || 0
  const minV = Number(bottom?.[m0]) || 0

  kpis.push({ label: `Total ${m0}`, value: compact(total) })
  kpis.push({ label: `Avg ${m0}`, value: compact(avg) })
  if (top) kpis.push({ label: `Top ${catCol}`, value: String(top[catCol]), hint: compact(maxV) })

  // -------- Insights ----------------------------------------------------------
  if (top && total > 0 && !isTime) {
    insights.push({ text: `${top[catCol]} leads on ${m0} with ${compact(maxV)} (${pct(maxV / total)} of the total).`, kind: "up" })
    const top3 = sorted.slice(0, 3).reduce((s, d) => s + (Number(d[m0]) || 0), 0)
    if (sorted.length > 3) {
      insights.push({
        text: `The top 3 ${catCol} account for ${pct(top3 / total)} of ${m0} — ${top3 / total > 0.6 ? "highly concentrated" : "fairly distributed"}.`,
        kind: top3 / total > 0.6 ? "warn" : "info",
      })
    }
    if (bottom && bottom !== top) insights.push({ text: `${bottom[catCol]} trails with ${compact(minV)} on ${m0}.`, kind: "down" })
  }
  if (isTime && vals.length >= 2) {
    const first = vals[0], last = vals[vals.length - 1]
    if (first !== 0) {
      const g = (last - first) / Math.abs(first)
      insights.push({
        text: `${m0} moved from ${compact(first)} to ${compact(last)} over the period — ${g >= 0 ? "up" : "down"} ${pct(Math.abs(g))}.`,
        kind: g >= 0 ? "up" : "down",
      })
    }
    const peak = sorted[0]
    if (peak) insights.push({ text: `Peak ${m0} of ${compact(maxV)} at ${peak[catCol]}.`, kind: "info" })
  }
  if (metricCols.length >= 2) {
    const a = data.map((d) => Number(d[metricCols[0]]) || 0)
    const b = data.map((d) => Number(d[metricCols[1]]) || 0)
    const r = pearson(a, b)
    if (Math.abs(r) >= 0.4) {
      insights.push({ text: `${metricCols[0]} and ${metricCols[1]} are ${r > 0 ? "positively" : "negatively"} correlated (r = ${r.toFixed(2)}).`, kind: r > 0 ? "up" : "down" })
    }
  }

  // -------- Charts: emit several complementary views --------------------------
  if (isTime) {
    if (metricCols.length > 1) {
      charts.push({ type: "multiLine", title: "Trends over time", subtitle: `${metricCols.join(", ")} across ${catCol}`, category: catCol, metrics: metricCols, data })
      charts.push({ type: "stackedArea", title: "Composition over time", subtitle: "stacked contribution of each measure", category: catCol, metrics: metricCols, data })
    } else {
      charts.push({ type: "line", title: `${m0} over ${catCol}`, subtitle: "trend line", category: catCol, metrics: [m0], data })
      charts.push({ type: "area", title: `${m0} — filled view`, subtitle: "magnitude over time", category: catCol, metrics: [m0], data })
      if (rows.length <= 24) charts.push({ type: "bar", title: `${m0} by ${catCol}`, subtitle: "period-by-period", category: catCol, metrics: [m0], data })
    }
  } else if (metricCols.length > 1) {
    const few = rows.length <= 8
    charts.push({ type: "groupedBar", title: "Side-by-side comparison", subtitle: `${metricCols.join(" vs ")} by ${catCol}`, category: catCol, metrics: metricCols, data })
    if (metricCols.length === 2) charts.push({ type: "composed", title: `${metricCols[0]} vs ${metricCols[1]}`, subtitle: "bars + line (dual axis)", category: catCol, metrics: metricCols, data })
    if (few) charts.push({ type: "radar", title: "Profile comparison", subtitle: "multi-measure shape per category", category: catCol, metrics: metricCols, data })
    charts.push({ type: "stackedBar", title: "Stacked totals", subtitle: "combined magnitude per category", category: catCol, metrics: metricCols, data })
  } else {
    const card = rows.length
    const allPositive = data.every((d) => Number(d[m0]) >= 0)
    // Primary ranking
    charts.push({ type: card > 12 ? "hbar" : "bar", title: `${m0} by ${catCol}`, subtitle: card > 12 ? "ranked (top to bottom)" : "by category", category: catCol, metrics: [m0], data: card > 12 ? sorted.slice(0, 20) : data })
    // Share view
    if (allPositive && card >= 2 && card <= 8) {
      charts.push({ type: "donut", title: `${m0} share`, subtitle: "part-to-whole", category: catCol, metrics: [m0], data })
    } else if (allPositive && card > 8 && card <= 40) {
      charts.push({ type: "treemap", title: `${m0} composition`, subtitle: "relative size by category", category: catCol, metrics: [m0], data: sorted.slice(0, 30) })
    }
    // Funnel for stage-like data
    if (STAGE_RE.test(catCol) && card >= 3 && card <= 8 && allPositive) {
      charts.push({ type: "funnel", title: `${m0} funnel`, subtitle: "stage-to-stage drop-off", category: catCol, metrics: [m0], data: sorted })
    }
  }

  return { single: null, kpis, charts, insights }
}
