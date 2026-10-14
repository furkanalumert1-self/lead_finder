<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { store, loadCampaigns, loadOverview, toast } from '../store'
import { usd, when, RUN_STATUS, ISSUE } from '../format'

const runs = ref<any[]>([])
const busy = ref<number | null>(null)
let timer = 0

async function refresh() {
  await loadCampaigns()
  runs.value = await api('/leads/api/runs')
  const live = runs.value.some(r => r.status === 'queued' || r.status === 'running')
  clearTimeout(timer)
  if (live) timer = window.setTimeout(refresh, 2000)
  else loadOverview()
}

async function run(id: number) {
  busy.value = id
  try { await api(`/leads/api/campaigns/${id}/run`, { method: 'POST' }); toast('Tarama başladı.'); await refresh() }
  catch (e) { toast(e instanceof Error ? e.message : String(e)) } finally { busy.value = null }
}
async function stop(runId: number) {
  await api(`/leads/api/runs/${runId}/stop`, { method: 'POST' }); toast('Durdurma istendi; sürmekte olan çağrı bitince durur.'); refresh()
}
async function toggle(c: any) {
  const status = c.status === 'active' ? 'paused' : 'active'
  await api(`/leads/api/campaigns/${c.id}`, { method: 'PUT', body: { ...c, status } }); refresh()
}
async function remove(c: any) {
  if (!confirm(`"${c.name}" silinsin mi? Leadler ve notları kalır.`)) return
  try { await api(`/leads/api/campaigns/${c.id}`, { method: 'DELETE' }); refresh() }
  catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}
function edit(c: any) { store.wizardEdit = c; store.wizardOpen = true }
function create() { store.wizardEdit = null; store.wizardOpen = true }
const live = (c: any) => c.last_run && ['queued', 'running'].includes(c.last_run.status)
const runsOf = (id: number) => runs.value.filter(r => r.campaign_id === id).slice(0, 5)

onMounted(refresh)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="page-h">
    <div><h1>Kampanyalar</h1><p>Sorgular, kaynak, limitler ve bütçe. Durdurma sürmekte olan çağrıyı bekler; yeni çağrı başlatmaz.</p></div>
    <button class="btn primary" type="button" @click="create">+ Yeni kampanya</button>
  </div>

  <div v-if="!store.campaigns.length" class="card empty">
    <h2>İlk kampanyanı oluştur</h2>
    <p>3 adım: hedef müşteri, kaynak ve sorgu, limitler. Anahtar bağlı değilse Demo kaynağıyla deneyebilirsin.</p>
    <button class="btn primary" type="button" @click="create">İlk kampanyanı oluştur</button>
  </div>

  <div class="stack" style="gap:12px">
    <article v-for="c in store.campaigns" :key="c.id" class="card">
      <div class="row" style="justify-content:space-between">
        <div>
          <h2 style="margin:0">{{ c.name }}</h2>
          <div class="row small muted" style="margin-top:4px">
            <span class="pill" :class="{ good: c.status === 'active', mid: c.status === 'paused' }">{{ { draft: 'Taslak', active: 'Aktif', paused: 'Duraklatıldı' }[c.status as string] }}</span>
            <span v-if="c.provider === 'demo'" class="pill demo">Demo</span>
            <span>Kaynak: {{ store.sources.discovery.find(s => s.key === c.provider)?.label || c.provider }}</span>
            <span>· {{ c.signal_type === 'hiring' ? 'İşe alım' : 'İçerik' }} sinyali</span>
            <span>· {{ c.result_limit }} aday / {{ c.enrich_limit }} e-posta</span>
            <span>· koşu bütçesi {{ usd(c.budget_run_micro) }}</span>
            <span v-if="c.schedule_daily">· her gün {{ String(c.schedule_hour).padStart(2, '0') }}:00</span>
          </div>
        </div>
        <div class="row">
          <button v-if="!live(c)" class="btn primary sm" type="button" :disabled="busy === c.id" @click="run(c.id)">Çalıştır</button>
          <button v-else class="btn sm danger" type="button" @click="stop(c.last_run.id)">Durdur</button>
          <button class="btn sm" type="button" @click="edit(c)">Düzenle</button>
          <button class="btn sm" type="button" @click="toggle(c)">{{ c.status === 'active' ? 'Duraklat' : 'Etkinleştir' }}</button>
          <button class="btn sm ghost danger" type="button" :disabled="live(c)" @click="remove(c)">Sil</button>
        </div>
      </div>
      <p class="small muted" style="margin:8px 0 0">Sorgular: {{ c.queries.join(' · ') }}</p>
      <h3>Son koşular</h3>
      <p v-if="!runsOf(c.id).length" class="muted small">Henüz koşu yok.</p>
      <ul v-else class="list">
        <li v-for="r in runsOf(c.id)" :key="r.id" style="align-items:flex-start">
          <div class="stack" style="gap:2px">
            <div class="row">
              <span class="pill" :class="{ good: r.status === 'succeeded', mid: r.status === 'partial' || r.status === 'running', bad: r.status === 'failed' }">{{ RUN_STATUS[r.status] }}</span>
              <span class="small muted">{{ when(r.created_at) }} · {{ r.trigger === 'scheduled' ? 'zamanlanmış' : 'manuel' }}</span>
            </div>
            <span v-for="(i, n) in r.issues.slice(0, 3)" :key="n" class="small"><b>{{ ISSUE[i.kind] || i.kind }}</b>{{ i.query ? ` (“${i.query}”)` : '' }}: {{ i.message }}</span>
          </div>
          <div class="small" style="text-align:right">
            {{ r.candidates }} aday · {{ r.qualified }} uygun · {{ r.new_leads }} yeni · {{ r.enriched }} e-posta<br />
            <span class="muted">API {{ usd(r.api_cost_micro) }} · LLM {{ usd(r.llm_cost_micro) }}</span>
          </div>
        </li>
      </ul>
    </article>
  </div>
</template>
