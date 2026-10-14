<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { store, toast } from '../store'
import { band, day, EMAIL_STATUS, safeUrl, STATUS, STATUS_ORDER, when } from '../format'

const props = defineProps<{ id: number }>()
const emit = defineEmits<{ close: [], changed: [] }>()
const lead = ref<any>(null)
const note = ref('')
const status = ref('')
const busy = ref(false)
const draft = ref('')
const enrichWith = ref('')
const closeBtn = ref<HTMLButtonElement | null>(null)

async function load() {
  lead.value = await api(`/leads/api/leads/${props.id}`)
  note.value = lead.value.note
  status.value = lead.value.status
  draft.value = ''
}
watch(() => props.id, load)
onMounted(async () => { await load(); await nextTick(); closeBtn.value?.focus() })

const enrichers = computed(() => store.sources.enrichment.filter(s => s.demo ? lead.value?.demo : s.state === 'connected'))
const canEnrich = computed(() => lead.value?.qualified && !lead.value?.email && lead.value?.person_name && lead.value?.domain)
const why = computed(() => {
  const l = lead.value
  if (!l) return ''
  const fresh = l.signal_date ? `${day(l.signal_date)} tarihli` : 'tarihi bilinmeyen'
  return `${fresh} ${l.signal_type === 'hiring' ? 'işe alım ilanı' : 'herkese açık paylaşım'}: ${l.summary || '—'}`
})

async function save() {
  busy.value = true
  try {
    lead.value = await api(`/leads/api/leads/${props.id}`, { method: 'PATCH', body: { status: status.value, note: note.value } })
    toast('Kaydedildi.'); emit('changed')
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) } finally { busy.value = false }
}
async function enrich() {
  if (!enrichWith.value) return
  busy.value = true
  try {
    lead.value = await api(`/leads/api/leads/${props.id}/enrich`, { method: 'POST', body: { provider: enrichWith.value } })
    toast(lead.value.email ? 'E-posta bulundu.' : 'E-posta bulunamadı.'); emit('changed')
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) } finally { busy.value = false }
}
async function makeDraft() { draft.value = (await api(`/leads/api/leads/${props.id}/draft`, { method: 'POST' })).draft }
async function suppress() {
  const kind = lead.value.email ? 'email' : lead.value.domain ? 'domain' : 'person_url'
  const value = lead.value.email || lead.value.domain || lead.value.person_url
  if (!value || !confirm(`${value} iletişim hariç tutma listesine eklensin mi? Tekrar zenginleştirilmez.`)) return
  await api('/leads/api/suppressions', { method: 'POST', body: { kind, value, reason: 'Lead çekmecesinden' } })
  toast('Hariç tutma listesine eklendi.'); await load(); emit('changed')
}
async function remove() {
  if (!confirm('Bu lead ve kanıtları kalıcı olarak silinsin mi?')) return
  await api(`/leads/api/leads/${props.id}`, { method: 'DELETE' }); emit('changed'); emit('close')
}
</script>

<template>
  <div class="scrim" @click="emit('close')" />
  <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-h" @keydown.esc="emit('close')">
    <div class="drawer-h">
      <div style="flex:1;min-width:0">
        <h2 id="drawer-h">{{ lead?.company || lead?.domain || 'Lead' }}</h2>
        <div v-if="lead" class="muted small">{{ [lead.person_name, lead.person_role, lead.location].filter(Boolean).join(' · ') || 'Kişi bilinmiyor' }}</div>
      </div>
      <button ref="closeBtn" class="btn ghost sm" type="button" aria-label="Kapat" @click="emit('close')">✕</button>
    </div>
    <div v-if="!lead" class="drawer-b"><div class="skeleton" /><div class="skeleton" /></div>
    <div v-else class="drawer-b">
      <div class="row">
        <span class="pill" :class="band(lead.score, lead.qualified).tone"><b>{{ lead.score }}</b>/100 · {{ band(lead.score, lead.qualified).label }}</span>
        <span v-if="lead.demo" class="pill demo">Demo</span>
        <span class="pill">Kaynak: {{ lead.provider }}</span>
      </div>

      <section><h3>Özet</h3><p style="margin:0">{{ lead.fit_reason }}</p>
        <p v-if="lead.domain" class="small muted" style="margin:4px 0 0">Domain: {{ lead.domain }}</p></section>

      <section><h3>Neden şimdi?</h3><p style="margin:0">{{ why }}</p></section>

      <section>
        <h3>Kaynak bağlantıları ({{ lead.evidence.length }})</h3>
        <p v-if="!lead.evidence.length" class="banner warn" style="margin:0">Kanıt yok: bu aday uygun lead sayılmaz.</p>
        <div v-for="e in lead.evidence" :key="e.id" class="ev">
          <a v-if="safeUrl(e.url)" :href="safeUrl(e.url)" target="_blank" rel="noopener noreferrer nofollow">{{ e.title || e.url }} ↗</a>
          <span v-else>{{ e.url }}</span>
          <span class="small muted">{{ day(e.signal_date) }} · {{ e.provider }} · bulundu {{ when(e.found_at) }}</span>
          <span v-if="e.snippet" class="small clip">{{ e.snippet }}</span>
        </div>
        <a v-if="lead.person_url && safeUrl(lead.person_url)" :href="safeUrl(lead.person_url)" target="_blank" rel="noopener noreferrer nofollow" class="small">Kişi profili ↗</a>
      </section>

      <section>
        <h3>Skor gerekçesi</h3>
        <div class="row small" style="margin-bottom:6px"><span class="pill">ICP {{ lead.score_fit }}/50</span><span class="pill">Sinyal {{ lead.score_signal }}/30</span><span class="pill">Güncellik {{ lead.score_recency }}/20</span></div>
        <ul class="notes small" style="margin:0;padding-left:18px"><li v-for="(n, i) in lead.score_notes" :key="i">{{ n }}</li></ul>
      </section>

      <section>
        <h3>İletişim doğrulaması</h3>
        <p style="margin:0">{{ lead.email || 'E-posta yok' }} <span class="pill">{{ EMAIL_STATUS[lead.email_status] }}</span></p>
        <p v-if="lead.last_enriched_at" class="small muted" style="margin:4px 0 0">Son enrichment: {{ when(lead.last_enriched_at) }}</p>
        <div v-if="canEnrich" class="row" style="margin-top:8px">
          <label class="sr" for="d-en">E-posta sağlayıcısı</label>
          <select id="d-en" v-model="enrichWith" class="input" style="width:auto">
            <option value="">Sağlayıcı seç…</option>
            <option v-for="s in enrichers" :key="s.key" :value="s.key">{{ s.label }}</option>
          </select>
          <button class="btn sm" type="button" :disabled="!enrichWith || busy" @click="enrich">E-posta bul</button>
        </div>
        <p v-if="canEnrich && enrichWith" class="small muted" style="margin:4px 0 0">{{ store.sources.enrichment.find(s => s.key === enrichWith)?.data_note }}</p>
        <p v-else-if="!lead.qualified" class="small muted" style="margin:4px 0 0">Enrichment yalnızca uygun (kanıtlı) adaylarda yapılır.</p>
      </section>

      <section>
        <h3>Durum ve not</h3>
        <div class="stack">
          <label class="sr" for="d-st">Durum</label>
          <select id="d-st" v-model="status" class="input"><option v-for="s in STATUS_ORDER" :key="s" :value="s">{{ STATUS[s] }}</option></select>
          <label class="sr" for="d-no">Not</label>
          <textarea id="d-no" v-model="note" class="input" rows="3" placeholder="Takip notu…" />
          <div class="row"><button class="btn primary sm" type="button" :disabled="busy" @click="save">Kaydet</button></div>
        </div>
      </section>

      <section>
        <h3>Mesaj taslağı</h3>
        <p class="small muted" style="margin:0 0 6px">Şablondan üretilir; hiçbir şey gönderilmez.</p>
        <button v-if="!draft" class="btn sm" type="button" @click="makeDraft">Kısa taslak oluştur</button>
        <textarea v-else v-model="draft" class="input" rows="7" aria-label="Mesaj taslağı" />
      </section>

      <section class="row" style="border-top:1px solid var(--line);padding-top:12px">
        <button class="btn sm" type="button" @click="suppress">İletişim hariç tut</button>
        <button class="btn sm danger" type="button" @click="remove">Leadi sil</button>
      </section>
    </div>
  </aside>
</template>
