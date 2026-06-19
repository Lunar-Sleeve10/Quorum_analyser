import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function LimitationsNotice() {
  return (
    <Card className="border-amber-500/40">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Limitations</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground space-y-1">
        <p>Some capabilities are intentionally limited in this preview.</p>
        <p>AI/ML API and Featherless usage is restricted due to credit constraints.</p>
        <p>Model availability may vary based on the configured providers.</p>
        <p>Certain advanced investigations may be rate-limited.</p>
      </CardContent>
    </Card>
  )
}
