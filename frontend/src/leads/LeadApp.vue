<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { api, ApiError, setOrg } from './api'
import { store, loadSources, loadOverview, loadIcps, loadCampaigns } from './store'
import { usd } from './format'
import OverviewPage from './pages/OverviewPage.vue'
import CampaignsPage from './pages/CampaignsPage.vue'
import LeadsPage from './pages/LeadsPage.vue'
import SourcesPage from './pages/SourcesPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import CampaignWizard from './pages/CampaignWizard.vue'

type View = 'overview' | 'campaigns' | 'leads' | 'sources' | 'settings'
const NAV: { id: View, label: string, icon: string }[] = [
  { id: 'overview', label: 'Genel Bakış', icon: 'M3 12h4l3 8 4-16 3 8h4' },
  { id: 'campaigns', label: 'Kampanyalar', icon: 'M4 6h16M4 12h10M4 18h7' },
  { id: 'leads', label: 'Leadler', icon: 'M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6M22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8' },
  { id: 'sources', label: 'Kaynaklar', icon: 'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6' },
  { id: 'settings', label: 'Ayarlar', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z' },
]

const view = ref<View>('overview')
const state = ref<'loading' | 'ready' | 'signin' | 'error'>('loading')
const error = ref('')
const menuOpen = ref(false)
const theme = ref(document.documentElement.dataset.theme || 'light')
const orgs = ref<{ slug: string, name: string }[]>([])
const org = ref('')

function fromHash(): View {
  const id = location.hash.replace(/^#\/?/, '') as View
  return NAV.some(n => n.id === id) ? id : 'overview'
}
function onHash() { view.value = fromHash(); menuOpen.value = false }

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme.value
  try { localStorage.setItem('leadradar-theme', theme.value) } catch { /* private mode */ }
}

async function boot() {
  state.value = 'loading'
  try {
    const list = await api<{ slug: string, name: string, active?: boolean }[]>('/orgs')
    orgs.value = list
    let saved = ''
    try { saved = localStorage.getItem('leadradar-org') || '' } catch { /* private mode */ }
    org.value = (list.find(o => o.slug === saved) || list.find(o => o.active) || list[0])?.slug || ''
    if (!org.value) { state.value = 'error'; error.value = 'Bu hesapta takım yok. Önce panelden bir takım oluşturun.'; return }
    setOrg(org.value)
    await Promise.all([loadSources(), loadOverview(), loadIcps(), loadCampaigns()])
    state.value = 'ready'
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { state.value = 'signin'; return }
    state.value = 'error'
    error.value = e instanceof Error ? e.message : String(e)
  }
}

watch(org, (slug, old) => {
  if (!old || !slug) return
  try { localStorage.setItem('leadradar-org', slug) } catch { /* private mode */ }
  setOrg(slug)
  boot()
})

const discovery = computed(() => store.sources.discovery.filter(s => !s.demo))
const sourceState = computed(() => {
  const connected = discovery.value.filter(s => s.state === 'connected').length
  if (connected) return { label: `${connected} kaynak bağlı`, tone: 'good' }
  if (discovery.value.some(s => s.state === 'error')) return { label: 'Kaynak hatalı', tone: 'bad' }
  return { label: 'Demo modu', tone: 'demo' }
})
const budget = computed(() => {
  const o = store.overview
  if (!o) return null
  const limit = o.limits?.month_limit_micro || 0
  return { used: o.month_api_cost_micro, limit, pct: limit ? Math.min(100, Math.round(o.month_api_cost_micro / limit * 100)) : 0 }
})

function goLeads() { location.hash = '#/leads' }
function newCampaign() { store.wizardEdit = null; store.wizardOpen = true }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') menuOpen.value = false }

onMounted(() => { onHash(); window.addEventListener('hashchange', onHash); window.addEventListener('keydown', onKey); boot() })
onBeforeUnmount(() => { window.removeEventListener('hashchange', onHash); window.removeEventListener('keydown', onKey) })
</script>

<template>
  <a class="skip" href="#main">İçeriğe geç</a>
  <div class="shell">
    <aside class="side" :class="{ open: menuOpen }" aria-label="Ana menü">
      <div class="brand"><span class="brand-mark" aria-hidden="true">◎</span> Lead Radar</div>
      <nav class="nav stack" style="gap:2px">
        <a v-for="n in NAV" :key="n.id" :href="`#/${n.id}`" :aria-current="view === n.id ? 'page' : undefined">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="n.icon" /></svg>
          {{ n.label }}
        </a>
      </nav>
      <div class="side-foot">
        <label v-if="orgs.length > 1" class="field"><span class="lbl">Takım</span>
          <select v-model="org" class="input"><option v-for="o in orgs" :key="o.slug" :value="o.slug">{{ o.name }}</option></select>
        </label>
        <button class="btn sm" type="button" @click="toggleTheme">{{ theme === 'dark' ? 'Açık tema' : 'Koyu tema' }}</button>
        <a href="/app" class="small">Treg paneline dön</a>
      </div>
    </aside>
    <div v-if="menuOpen" class="scrim" style="z-index:45" @click="menuOpen = false" />

    <div class="main">
      <header class="top">
        <button class="btn ghost menu-btn" type="button" aria-label="Menüyü aç" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <div class="search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          <label class="sr" for="global-search">Leadlerde ara</label>
          <input id="global-search" v-model="store.search" type="search" placeholder="Şirket, kişi, not ara…" @keydown.enter="goLeads" />
        </div>
        <div class="top-right">
          <a href="#/sources" class="pill" :class="sourceState.tone"><span class="dot" aria-hidden="true" />{{ sourceState.label }}</a>
          <a v-if="budget" href="#/settings" class="pill hide-sm" :title="'Bu ay gerçekleşen sağlayıcı harcaması / aylık sınır'">
            Bütçe: {{ usd(budget.used) }} / {{ budget.limit ? usd(budget.limit) : 'sınır yok' }}
          </a>
          <button class="btn primary" type="button" :disabled="state !== 'ready'" @click="newCampaign">+ Yeni kampanya</button>
        </div>
      </header>

      <main id="main" class="content" tabindex="-1">
        <div v-if="state === 'loading'" class="stack" aria-busy="true"><div class="skeleton" style="width:240px;height:28px" /><div class="skeleton" /><div class="skeleton" style="width:60%" /></div>
        <div v-else-if="state === 'signin'" class="card empty">
          <h2>Oturum açın</h2>
          <p>Lead Radar, Treg hesabınızla çalışır. Yerel tek kullanıcı modunda bu sayfa otomatik açılır.</p>
          <a class="btn primary" href="/app">Treg'e giriş yap</a>
        </div>
        <div v-else-if="state === 'error'" class="banner err" role="alert"><div><b>Yüklenemedi.</b> {{ error }} <button class="btn sm" type="button" @click="boot">Tekrar dene</button></div></div>
        <template v-else>
          <OverviewPage v-if="view === 'overview'" />
          <CampaignsPage v-else-if="view === 'campaigns'" />
          <LeadsPage v-else-if="view === 'leads'" />
          <SourcesPage v-else-if="view === 'sources'" />
          <SettingsPage v-else-if="view === 'settings'" />
        </template>
      </main>
    </div>
  </div>
  <CampaignWizard v-if="store.wizardOpen" />
  <div v-if="store.toast" class="toast" role="status">{{ store.toast }}</div>
</template>
