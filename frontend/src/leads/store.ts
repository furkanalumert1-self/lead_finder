import { reactive } from 'vue'
import { api } from './api'

export interface Source {
  key: string, kind: string, label: string, demo: boolean, service: string, data_note: string,
  state: 'demo' | 'connected' | 'missing' | 'error', missing: string[], health: string | null,
  last_checked: string | null, price: { ceiling_micro: number, unit_micro: number, source: string, checked: string } | null
}

export const store = reactive({
  sources: { discovery: [] as Source[], enrichment: [] as Source[], registry_token: false },
  overview: null as any,
  icps: [] as any[],
  campaigns: [] as any[],
  wizardOpen: false,
  wizardEdit: null as any,
  search: '',
  toast: '' as string,
})

export async function loadSources() { store.sources = await api('/leads/api/sources') }
export async function loadOverview() { store.overview = await api('/leads/api/overview') }
export async function loadIcps() { store.icps = await api('/leads/api/icps') }
export async function loadCampaigns() { store.campaigns = await api('/leads/api/campaigns') }

let toastTimer = 0
export function toast(message: string) {
  store.toast = message
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { store.toast = '' }, 4000)
}
