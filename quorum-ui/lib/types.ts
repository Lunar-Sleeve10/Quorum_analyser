export type Topology = "governed_chain" | "investigation_board"

export interface Quota {
  queries_remaining: number
  queries_limit: number
  followups_per_investigation: number
  session_token: string
}

export interface RecentItem {
  id: string
  question: string
  topology: Topology
  status: string
  confidence: number | null
}

export interface Dashboard {
  active_investigations: number
  review_boards: number
  completed: number
  escalations: number
  governance_events: number
  avg_confidence: number | null
  queries_remaining: number
  recent: RecentItem[]
  session_token: string
}

export interface Investigation {
  id: string
  question: string
  normalized_question: string
  topology: Topology
  status: string
  confidence: number | null
  risk_level: string
  approval_required: boolean
  estimated_cost_usd: number | null
  data_source_id: string | null
  scope_id: string | null
  parent_investigation_id: string | null
  followups_used: number
  created_at: string | null
}

export interface Finding {
  factor: string
  label: string
  verdict: string
  evidence: string
}

export interface BoardDecision {
  headline: string
  primary_factor: string | null
  recommendation: string
  confidence: string
}

export interface AuthorizedResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  chart_type: string | null
}

export interface FollowupRef {
  id: string
  question: string
  status: string
  topology: Topology
  confidence: number | null
}

export interface InvestigationDetail extends Investigation {
  findings: Finding[]
  board_decision: BoardDecision | null
  authorized_result: AuthorizedResult | null
  followups: FollowupRef[]
  cost: CostInfo | null
  governance: GovEvent[]
  sql: string | null
}

export interface RoomMessage {
  id: string
  ts: string | null
  sender: string
  target: string
  kind: string
  summary: string
  status: string
}

export interface Room {
  investigation_id: string
  topology: Topology
  status: string
  confidence: number | null
  band_room_id: string | null
  active_agents: string[]
  shared_context: Record<string, unknown>
  messages: RoomMessage[]
}

export interface SystemStatus {
  database: { url_scheme: string; ok: boolean }
  band_configured: boolean
  llm_backend: string
  cached_plans: number
  investigations: number
  data_sources: number
  rooms: number
  findings: number
  dictionaries: number
  semantic_catalog: boolean
  credentials_encrypted_at_rest: boolean
}

export interface DataSource {
  id: string
  kind: string
  display_name: string
  is_sample: boolean
  status: string
  has_credentials?: boolean
}

export interface CostEstimate {
  engine?: string
  risk_level?: string
  within_budget?: boolean
  estimated_rows_scanned?: number | null
  estimated_bytes_scanned?: number | null
  estimated_cost_usd?: number | null
  method?: string
}

export interface CostInfo {
  risk_level?: string
  estimate?: CostEstimate
}

export interface GovEvent {
  type: string
  detail: Record<string, unknown>
  ts: string | null
}

export interface SchemaInfo {
  tables: { name: string; columns: string[] }[]
}
