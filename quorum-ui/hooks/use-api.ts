"use client"

import { useMutation, useQuery, useQueryClient, type Query } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { InvestigationDetail } from "@/lib/types"

const terminal = (s?: string) => s === "completed" || s === "error" || s === "escalated"

export const useQuota = () => useQuery({ queryKey: ["quota"], queryFn: api.quota })
export const useDashboard = () =>
  useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 5000 })
export const useSystemStatus = () =>
  useQuery({ queryKey: ["system"], queryFn: api.systemStatus, refetchInterval: 10000 })
export const useDataSources = () => useQuery({ queryKey: ["data-sources"], queryFn: api.dataSources })
export const useInvestigations = () =>
  useQuery({ queryKey: ["investigations"], queryFn: api.investigations, refetchInterval: 4000 })

export const useInvestigation = (id: string | null) =>
  useQuery({
    queryKey: ["investigation", id],
    queryFn: () => api.investigation(id as string),
    enabled: !!id,
    refetchInterval: (q: Query<InvestigationDetail>) =>
      terminal(q.state.data?.status) ? false : 2000,
  })

export const useRoom = (id: string | null) =>
  useQuery({
    queryKey: ["room", id],
    queryFn: () => api.room(id as string),
    enabled: !!id,
    refetchInterval: 2000,
  })

export function useCreateInvestigation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { question: string; dataSourceId?: string | null; scopeId?: string | null }) =>
      api.createInvestigation(v.question, v.dataSourceId, v.scopeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investigations"] })
      qc.invalidateQueries({ queryKey: ["dashboard"] })
      qc.invalidateQueries({ queryKey: ["quota"] })
    },
  })
}

export function useFollowup(parentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => api.followup(parentId, question),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investigation", parentId] })
      qc.invalidateQueries({ queryKey: ["investigations"] })
    },
  })
}

export const useSchema = (id: string | null, enabled: boolean) =>
  useQuery({ queryKey: ["schema", id], queryFn: () => api.schema(id as string), enabled: enabled && !!id })

export function useConnectExternal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { kind: string; displayName: string; connectionMeta: Record<string, unknown>; credentials: Record<string, unknown> }) =>
      api.connectExternal(v.kind, v.displayName, v.connectionMeta, v.credentials),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  })
}

export function useUploadDataSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadDataSource(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["data-sources"] }),
  })
}


export function useDeleteDataSource() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => api.deleteDataSource(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["data-sources"] })
    },
  })
}