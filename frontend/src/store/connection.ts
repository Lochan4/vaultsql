import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ConnectionState {
  alias: string | null          // active DB connection alias
  dialect: string | null        // postgresql | mysql | sqlite | mssql
  isConnected: boolean

  setConnection: (alias: string, dialect: string) => void
  clearConnection: () => void
}

export const useConnectionStore = create<ConnectionState>()(
  persist(
    (set) => ({
      alias: null,
      dialect: null,
      isConnected: false,

      setConnection: (alias, dialect) =>
        set({ alias, dialect, isConnected: true }),

      clearConnection: () =>
        set({ alias: null, dialect: null, isConnected: false }),
    }),
    { name: 'vaultsql-connection' }
  )
)
