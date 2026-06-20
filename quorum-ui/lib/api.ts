import { useSession } from "@/store/session"
import type {
  Quota, Dashboard, Investigation, InvestigationDetail, Room, SystemStatus, DataSource, SchemaInfo,
} from "@/lib/types"

// Strip any trailing slash so `${BASE}${path}` never produces a "//" path
// (a trailing slash in NEXT_PUBLIC_API_BASE_URL yields 404s like //data-sources).
const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "")

// Single shared session-token key, also used by public/cover.html, so the cover
// page and the dashboard stay on ONE session. A stable session_id keeps Band
// room reuse working (one room per session+data-source); without sharing, each
// surface churns sessions and the backend mints a new room every time.
const TOKEN_KEY = "quorum_token"

function readToken(): string | null {
  let token = useSession.getState().token
  if (!token && typeof window !== "undefined") {
    token = window.localStorage.getItem(TOKEN_KEY)
    if (token) useSession.getState().setToken(token)
  }
  return token
}

function persistToken(token: string): void {
  useSession.getState().setToken(token)
  if (typeof window !== "undefined") {
    try { window.localStorage.setItem(TOKEN_KEY, token) } catch {}
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = readToken()
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (token) headers["X-Session-Token"] = token
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? res.statusText)
  if (data && typeof data === "object" && (data as { session_token?: string }).session_token) {
    persistToken((data as { session_token: string }).session_token)
  }
  return data as T
}

export const api = {
  quota: () => req<Quota>("/quota"),
  dashboard: () => req<Dashboard>("/dashboard/summary"),
  systemStatus: () => req<SystemStatus>("/system/status"),
  dataSources: () => req<DataSource[]>("/data-sources"),
  deleteDataSource: (id: string) =>
  req<{ ok: boolean }>(`/data-sources/${id}`, {
    method: "DELETE",
  }),
  investigations: () => req<Investigation[]>("/investigations"),
  investigation: (id: string) => req<InvestigationDetail>(`/investigations/${id}`),
  room: (id: string) => req<Room>(`/rooms/${id}`),
  createInvestigation: (question: string, dataSourceId?: string | null, scopeId?: string | null) =>
    req<Investigation & { queries_remaining: number }>("/investigations", {
      method: "POST",
      body: JSON.stringify({ question, data_source_id: dataSourceId ?? null, scope_id: scopeId ?? null }),
    }),
  followup: (id: string, question: string) =>
    req<Investigation>(`/investigations/${id}/followup`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  schema: (id: string) => req<SchemaInfo>(`/data-sources/${id}/schema`),
  connectExternal: (kind: string, displayName: string, connectionMeta: Record<string, unknown>, credentials: Record<string, unknown>) =>
    req<{ id: string; credentials_encrypted: boolean }>("/data-sources/connect", {
      method: "POST",
      body: JSON.stringify({ kind, display_name: displayName, connection_meta: connectionMeta, credentials }),
    }),
  createScope: (dataSourceId: string, tables: string[], columns: Record<string, string[]>) =>
    req<{ id: string }>("/schema-scopes", {
      method: "POST",
      body: JSON.stringify({ data_source_id: dataSourceId, tables, columns }),
    }),
  uploadDataSource: async (file: File) => {
    const token = readToken()
    const fd = new FormData()
    fd.append("file", file)
    const res = await fetch(`${BASE}/data-sources/upload`, {
      method: "POST",
      headers: token ? { "X-Session-Token": token } : undefined,
      body: fd,
    })
    if (!res.ok) throw new Error(res.statusText)
    return (await res.json()) as { id: string; display_name: string; kind: string }
  },
}

export const streamUrl = (id: string) => `${BASE}/rooms/${id}/stream`
