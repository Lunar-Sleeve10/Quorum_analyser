"use client"

import { Button } from "@/components/ui/button"
import { buildMarkdown } from "@/lib/report"
import type { InvestigationDetail, RoomMessage } from "@/lib/types"

function download(name: string, text: string, type: string) {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export function ReportActions({ inv, messages }: { inv: InvestigationDetail; messages: RoomMessage[] }) {
  const md = () => download(`report_${inv.id}.md`, buildMarkdown(inv, messages), "text/markdown")
  const pdf = async () => {
    const { jsPDF } = await import("jspdf")
    const doc = new jsPDF({ unit: "pt", format: "a4" })
    const text = buildMarkdown(inv, messages).replace(/[#*`>]/g, "")
    doc.setFontSize(10)
    doc.text(doc.splitTextToSize(text, 510), 40, 50)
    doc.save(`report_${inv.id}.pdf`)
  }
  return (
    <div className="flex gap-2">
      <Button variant="outline" size="sm" onClick={md}>Export Markdown</Button>
      <Button variant="outline" size="sm" onClick={pdf}>Export PDF</Button>
    </div>
  )
}
