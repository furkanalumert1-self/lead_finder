<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { store, loadOverview, toast } from '../store'
import { band, day, EMAIL_STATUS, STATUS, STATUS_ORDER } from '../format'
import LeadDrawer from './LeadDrawer.vue'

const f = reactive({ status: '', qualified: '', campaign_id: '', min_score: '', sort: 'score', demo: '', email: '' })
const data = ref<{ total: number, leads: any[] }>({ total: 0, leads: [] })
const state = ref<'loading' | 'ready' | 'error'>('loading')
const error = ref('')
const open = ref<number | null>(null)
const showAdd = ref(false)
const add = reactive({ company: '', domain: '', person_name: '', person_role: '', url: '', email: '', note: '' })
const fileInput = ref<HTMLInputElement | null>(null)

const query = computed(() => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) if (v) p.set(k, String(v))
  if (store.search.trim()) p.set('q', store.search.trim())
  return p.toString()
})

async function load() {
  state.value = 'loading'
  try { data.value = await api(`/leads/api/leads?${query.value}`); state.value = 'ready' }
  catch (e) { state.value = 'error'; error.value = e instanceof Error ? e.message : String(e) }
}
let debounce = 0
watch(query, () => { clearTimeout(debounce); debounce = window.setTimeout(load, 200) })

// A fetch, not a navigation: the team travels in the X-Treg-Org header, which a link cannot send.
async function exportCsv() {
  try {
    const text = await api<string>(`/leads/api/leads.csv?${query.value}`, { raw: true })
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `leadler-${new Date().toISOString().slice(0, 10)}.csv` })
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}

async function importCsv(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const r = await api('/leads/api/leads/import', { method: 'POST', body: { csv: await file.text() } })
    toast(`İçe aktarıldı: ${r.created} yeni, ${r.merged} birleşti, ${r.skipped} atlandı${r.suppressed ? `, ${r.suppressed} hariç tutma listesinde` : ''}.`)
    load(); loadOverview()
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
  if (fileInput.value) fileInput.value.value = ''
}

async function addLead() {
  try {
    const r = await api('/leads/api/leads', { method: 'POST', body: add })
    toast(r.created ? 'Lead eklendi.' : r.merged ? 'Mevcut leadle birleştirildi.' : 'Şirket, domain, profil veya kanıt URL\'si gerekli.')
    Object.assign(add, { company: '', domain: '', person_name: '', person_role: '', url: '', email: '', note: '' })
    showAdd.value = false
    load()
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}

function onRowKey(e: KeyboardEvent, id: number) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open.value = id } }
function onChanged() { load(); loadOverview() }
function create() { store.wizardEdit = null; store.wizardOpen = true }
const filtered = computed(() => !!store.search.trim() || Object.entries(f).some(([k, v]) => v && k !== 'sort'))
const anyDemo = computed(() => data.value.leads.some(l => l.demo))
const signalLabel = (l: any) => l.signal_type === 'hiring' ? 'İşe alım' : l.signal_type === 'content' ? 'İçerik' : (l.provider === 'csv' ? 'CSV' : 'Manuel')

onMounted(load)
</script>

<template>
  <div class="page-h">
    <div><h1>Leadler</h1><p>{{ data.total }} lead · skor kurallarla hesaplanır, satın alma olasılığı değildir.</p></div>
    <div class="row">
      <button class="btn" type="button" @click="showAdd = !showAdd" :aria-expanded="showAdd">+ Elle ekle</button>
      <label class="btn" for="csv-in">CSV içe aktar</label>
      <input id="csv-in" ref="fileInput" class="sr" type="file" accept=".csv,text/csv" @change="importCsv" />
      <button class="btn" type="button" :disabled="!data.total" @click="exportCsv">CSV dışa aktar</button>
    </div>
  </div>

  <div v-if="anyDemo" class="banner demo" role="note"><span class="pill demo">Demo</span><div>Listede demo veri var. Demo satırlar gerçek şirketler değildir; Ayarlar'dan silebilirsiniz.</div></div>

  <form v-if="showAdd" class="card" style="margin-bottom:12px" @submit.prevent="addLead">
    <h2>Elle lead ekle</h2>
    <div class="form-grid">
      <div class="field"><label for="a-co">Şirket</label><input id="a-co" v-model="add.company" /></div>
      <div class="field"><label for="a-do">Domain</label><input id="a-do" v-model="add.domain" placeholder="ornek.com" /></div>
      <div class="field"><label for="a-pn">Kişi</label><input id="a-pn" v-model="add.person_name" /></div>
      <div class="field"><label for="a-pr">Rol</label><input id="a-pr" v-model="add.person_role" /></div>
      <div class="field"><label for="a-url">Kanıt URL'si</label><input id="a-url" v-model="add.url" placeholder="https://…" /><span class="hint">Kanıtsız lead uygun sayılmaz.</span></div>
      <div class="field"><label for="a-em">E-posta</label><input id="a-em" v-model="add.email" type="email" /></div>
      <div class="field wide"><label for="a-no">Not</label><input id="a-no" v-model="add.note" /></div>
    </div>
    <div class="row" style="margin-top:12px"><button class="btn primary" type="submit">Ekle</button><button class="btn" type="button" @click="showAdd = false">Vazgeç</button></div>
  </form>

  <div class="filters" role="group" aria-label="Filtreler">
    <label class="sr" for="f-st">Durum</label>
    <select id="f-st" v-model="f.status"><option value="">Tüm durumlar</option><option v-for="s in STATUS_ORDER" :key="s" :value="s">{{ STATUS[s] }}</option></select>
    <label class="sr" for="f-q">Uygunluk</label>
    <select id="f-q" v-model="f.qualified"><option value="">Tüm adaylar</option><option value="1">Yalnızca uygun</option></select>
    <label class="sr" for="f-c">Kampanya</label>
    <select id="f-c" v-model="f.campaign_id"><option value="">Tüm kampanyalar</option><option v-for="c in store.campaigns" :key="c.id" :value="String(c.id)">{{ c.name }}</option></select>
    <label class="sr" for="f-ms">En düşük skor</label>
    <select id="f-ms" v-model="f.min_score"><option value="">Her skor</option><option value="40">40+</option><option value="60">60+</option><option value="80">80+</option></select>
    <label class="sr" for="f-d">Veri</label>
    <select id="f-d" v-model="f.demo"><option value="">Gerçek + demo</option><option value="0">Yalnızca gerçek</option></select>
    <label class="sr" for="f-e">E-posta</label>
    <select id="f-e" v-model="f.email"><option value="">E-posta: hepsi</option><option value="1">E-postası olan</option></select>
    <label class="sr" for="f-so">Sıralama</label>
    <select id="f-so" v-model="f.sort"><option value="score">Sırala: skor</option><option value="recent">Sırala: en yeni keşif</option><option value="signal">Sırala: sinyal tarihi</option><option value="company">Sırala: şirket</option></select>
  </div>

  <div v-if="state === 'loading' && !data.leads.length" class="card stack" aria-busy="true"><div class="skeleton" /><div class="skeleton" /><div class="skeleton" style="width:70%" /></div>
  <div v-else-if="state === 'error'" class="banner err" role="alert">Leadler yüklenemedi: {{ error }} <button class="btn sm" type="button" @click="load">Tekrar dene</button></div>
  <div v-else-if="!data.leads.length" class="card empty">
    <template v-if="filtered">
      <h2>Filtreye uyan lead yok</h2><p>Filtreleri gevşetin ya da aramayı temizleyin.</p>
    </template>
    <template v-else>
      <h2>Henüz lead yok</h2><p>İlk kampanyanı oluştur ya da CSV içe aktar.</p>
      <button class="btn primary" type="button" @click="create">İlk kampanyanı oluştur</button>
    </template>
  </div>
  <template v-else>
    <div class="table-wrap">
      <table class="leads">
        <thead><tr><th scope="col">Şirket / Kişi</th><th scope="col">Sinyal</th><th scope="col">Uygunluk</th><th scope="col">Tarih</th><th scope="col">Durum</th><th scope="col">E-posta</th></tr></thead>
        <tbody>
          <tr v-for="l in data.leads" :key="l.id" tabindex="0" :aria-label="`${l.company || l.domain || 'Lead'} detayını aç`" @click="open = l.id" @keydown="onRowKey($event, l.id)">
            <td>
              <div class="cell-main">{{ l.company || l.domain || '—' }} <span v-if="l.demo" class="pill demo">Demo</span></div>
              <div class="cell-sub">{{ [l.person_name, l.person_role].filter(Boolean).join(' · ') || 'Kişi bilinmiyor' }}{{ l.location ? ' · ' + l.location : '' }}</div>
            </td>
            <td><div class="cell-sub">{{ signalLabel(l) }}</div><div class="clip">{{ l.summary || '—' }}</div></td>
            <td>
              <div class="score"><b>{{ l.score }}</b><span class="pill" :class="band(l.score, l.qualified).tone">{{ band(l.score, l.qualified).label }}</span></div>
              <div class="cell-sub clip" style="max-width:220px">{{ l.fit_reason }}</div>
            </td>
            <td><div>{{ day(l.signal_date) }}</div><div class="cell-sub">keşif {{ day(l.discovered_at) }}</div></td>
            <td><span class="pill">{{ STATUS[l.status] }}</span></td>
            <td><div>{{ l.email || '—' }}</div><div class="cell-sub">{{ EMAIL_STATUS[l.email_status] }}</div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="lead-cards">
      <button v-for="l in data.leads" :key="l.id" class="lead-card" type="button" @click="open = l.id">
        <div class="row" style="justify-content:space-between;width:100%"><b>{{ l.company || l.domain || '—' }}</b><span class="pill">{{ STATUS[l.status] }}</span></div>
        <span class="muted small">{{ [l.person_name, l.person_role].filter(Boolean).join(' · ') || 'Kişi bilinmiyor' }}</span>
        <span class="clip small">{{ l.summary }}</span>
        <div class="row"><b>{{ l.score }}</b><span class="pill" :class="band(l.score, l.qualified).tone">{{ band(l.score, l.qualified).label }}</span><span v-if="l.demo" class="pill demo">Demo</span><span class="small muted">{{ day(l.signal_date) }}</span></div>
      </button>
    </div>
  </template>

  <LeadDrawer v-if="open !== null" :id="open" @close="open = null" @changed="onChanged" />
</template>
