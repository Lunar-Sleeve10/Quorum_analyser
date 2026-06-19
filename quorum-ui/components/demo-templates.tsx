"use client"

const TEMPLATES = [
  "Top customers by revenue",
  "Best selling products",
  "Monthly revenue trends",
  "Sales by region",
  "Customer retention",
  "Profitability analysis",
]

export function DemoTemplates({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {TEMPLATES.map((t) => (
        <button
          key={t}
          onClick={() => onPick(t)}
          className="rounded-full border border-border px-3 py-1 text-xs hover:bg-accent/50"
        >
          {t}
        </button>
      ))}
    </div>
  )
}
