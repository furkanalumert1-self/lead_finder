<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { store, loadIcps, loadOverview, toast } from '../store'
import { toMicro, usd, when } from '../format'

const s = reactive({ run: '', day: '', month: '', retention_days: 365, ttl_search: 24, ttl_email: 720 })
const sup = ref<any[]>([])
const newSup = reactive({ kind: 'domain', value: '', reason: '' })
const icp = reactive<any>({ id: null, name: '', product: '', website: '', sectors: '', geographies: '', sizes: '', roles: '', problems: '', competitors: '', exclusions: '' })
const LISTS = ['sectors', 'geographies', 'sizes', 'roles', 'problems', 'competitors', 'exclusions']
const LABELS: Record<string, string> = { sectors: 'Sektörler', geographies: 'Ülke / şehir', sizes: 'Şirket büyüklüğü', roles: 'Karar verici rolleri', problems: 'Problem ifadeleri', competitors: 'Rakipler', exclusions: 'Dışlama ölçütleri' }

async function load() {
  const v = await api('/leads/api/settings')
  Object.assign(s, { run: v.run_limit_micro ? String(v.run_limit_micro / 1e6) : '', day: v.day_limit_micro ? String(v.day_limit_micro / 1e6) : '',
    month: v.month_limit_micro ? String(v.month_limit_micro / 1e6) : '', retention_days: v.retention_days,
    ttl_search: v.cache_ttl_hours.search, ttl_email: v.cache_ttl_hours.email })
  sup.value = await api('/leads/api/suppressions')
  await loadIcps()
  const first = store.icps[0]
  if (first) { Object.assign(icp, first); for (const k of LISTS) icp[k] = (first[k] || []).join(', ') }
}

async function saveLimits() {
  try {
    await api('/leads/api/settings', { method: 'PUT', body: {
      day_limit_micro: toMicro(s.day), month_limit_micro: toMicro(s.month),
      retention_days: Number(s.retention_days), cache_ttl_hours: { search: Number(s.ttl_search), email: Number(s.ttl_email) } } })
    toast('Ayarlar kaydedildi.'); loadOverview()
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}
async function saveIcp() {
  try {
    const body = { ...icp, name: icp.name || 'Hedef müşteri' }
    await api(icp.id ? `/leads/api/icps/${icp.id}` : '/leads/api/icps', { method: icp.id ? 'PUT' : 'POST', body })
    toast('ICP kaydedildi. Yeni skorlar bir sonraki taramada uygulanır.'); load()
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}
async function addSup() {
  try { await api('/leads/api/suppressions', { method: 'POST', body: newSup }); newSup.value = ''; newSup.reason = ''; sup.value = await api('/leads/api/suppressions'); toast('Hariç tutma listesine eklendi.') }
  catch (e) { toast(e instanceof Error ? e.message : String(e)) }
}
async function delSup(id: number) { await api(`/leads/api/suppressions/${id}`, { method: 'DELETE' }); sup.value = await api('/leads/api/suppressions') }
async function purge() {
  if (!confirm(`${s.retention_days} günden eski (dokunulmamış) leadler ve süresi geçmiş cache silinsin mi?`)) return
  const r = await api('/leads/api/retention/purge', { method: 'POST' }); toast(`${r.leads_deleted} lead, ${r.cache_deleted} cache kaydı silindi.`); loadOverview()
}
async function deleteDemo() {
  if (!confirm('Tüm demo leadler silinsin mi?')) return
  const r = await api('/leads/api/leads/delete-demo', { method: 'POST' }); toast(`${r.deleted} demo lead silindi.`); loadOverview()
}
onMounted(load)
</script>

<template>
  <div class="page-h"><div><h1>Ayarlar</h1><p>Hedef müşteri, bütçe sınırları, veri saklama ve iletişim hariç tutma listesi.</p></div></div>

  <div class="grid cols-2">
    <form class="card" @submit.prevent="saveIcp">
      <h2>Hedef müşteri (ICP)</h2>
      <p class="small muted" style="margin-top:0">Boş alanlar “bilinmiyor” sayılır ve puan vermez.</p>
      <div class="form-grid">
        <div class="field wide"><label for="s-pr">Ürün / hizmet</label><input id="s-pr" v-model="icp.product" /></div>
        <div class="field wide"><label for="s-web">Web sitesi</label><input id="s-web" v-model="icp.website" placeholder="https://" /></div>
        <div v-for="k in LISTS" :key="k" class="field" :class="{ wide: k === 'problems' }"><label :for="`s-${k}`">{{ LABELS[k] }}</label><input :id="`s-${k}`" v-model="icp[k]" /></div>
      </div>
      <div class="row" style="margin-top:12px"><button class="btn primary" type="submit">ICP'yi kaydet</button></div>
    </form>

    <div class="stack" style="gap:16px">
      <form class="card" @submit.prevent="saveLimits">
        <h2>Bütçe sınırları (USD)</h2>
        <p class="small muted" style="margin-top:0">Sınır girilmemişse ücretli çağrı yapılmaz. Demo her zaman ücretsizdir. Sınırlar sunucuda, her çağrıdan önce uygulanır.</p>
        <div class="form-grid">
          <div class="field"><label for="s-day">Günlük</label><input id="s-day" v-model="s.day" inputmode="decimal" placeholder="örn. 1" /></div>
          <div class="field"><label for="s-month">Aylık</label><input id="s-month" v-model="s.month" inputmode="decimal" placeholder="örn. 10" /></div>
        </div>
        <p v-if="store.overview" class="small" style="margin:8px 0 0">Bu ay: {{ usd(store.overview.month_api_cost_micro) }} · bugün: {{ usd(store.overview.day_api_cost_micro) }}<span v-if="store.overview.month_uncertain_micro"> · belirsiz (zaman aşımı) rezerv {{ usd(store.overview.month_uncertain_micro) }}</span></p>
        <h3>Cache süresi (saat)</h3>
        <div class="form-grid">
          <div class="field"><label for="s-ts">Arama sonuçları</label><input id="s-ts" v-model="s.ttl_search" type="number" min="0" /></div>
          <div class="field"><label for="s-te">E-posta sonuçları</label><input id="s-te" v-model="s.ttl_email" type="number" min="0" /></div>
        </div>
        <h3>Veri saklama</h3>
        <div class="field"><label for="s-ret">Dokunulmayan leadleri sakla (gün)</label><input id="s-ret" v-model="s.retention_days" type="number" min="7" /></div>
        <div class="row" style="margin-top:12px"><button class="btn primary" type="submit">Kaydet</button><button class="btn" type="button" @click="purge">Şimdi temizle</button><button class="btn danger" type="button" @click="deleteDemo">Demo verileri sil</button></div>
      </form>

      <section class="card">
        <h2>İletişim hariç tutma listesi</h2>
        <p class="small muted" style="margin-top:0">Listedekiler uygun lead sayılmaz ve enrichment'e gönderilmez.</p>
        <form class="row" @submit.prevent="addSup">
          <label class="sr" for="s-sk">Tür</label>
          <select id="s-sk" v-model="newSup.kind" class="input" style="width:auto"><option value="domain">Domain</option><option value="email">E-posta</option><option value="person_url">Profil URL</option></select>
          <label class="sr" for="s-sv">Değer</label>
          <input id="s-sv" v-model="newSup.value" class="input" style="flex:1;min-width:140px" placeholder="ornek.com" />
          <button class="btn sm primary" type="submit" :disabled="!newSup.value">Ekle</button>
        </form>
        <p v-if="!sup.length" class="muted small">Liste boş.</p>
        <ul v-else class="list"><li v-for="x in sup" :key="x.id"><span><span class="pill">{{ { domain: 'Domain', email: 'E-posta', person_url: 'Profil' }[x.kind as string] }}</span> {{ x.value }} <span class="small muted">{{ when(x.created_at) }}</span></span><button class="btn sm ghost danger" type="button" :aria-label="`${x.value} kaldır`" @click="delSup(x.id)">Kaldır</button></li></ul>
      </section>
    </div>
  </div>
</template>
