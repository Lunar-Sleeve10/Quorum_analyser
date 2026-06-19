import { create } from "zustand"
import { persist } from "zustand/middleware"

interface SessionState {
  token: string | null
  currentInvestigationId: string | null
  dataSourceId: string | null
  saved: string[]
  setToken: (t: string) => void
  setCurrent: (id: string | null) => void
  setDataSource: (id: string | null) => void
  toggleSaved: (id: string) => void
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      token: null,
      currentInvestigationId: null,
      dataSourceId: null,
      saved: [],
      setToken: (token) => set({ token }),
      setCurrent: (currentInvestigationId) => set({ currentInvestigationId }),
      setDataSource: (dataSourceId) => set({ dataSourceId }),
      toggleSaved: (id) =>
        set((s) => ({ saved: s.saved.includes(id) ? s.saved.filter((x) => x !== id) : [...s.saved, id] })),
    }),
    { name: "quorum-session" },
  ),
)
