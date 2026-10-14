<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { store, loadCampaigns, loadIcps, loadOverview, toast } from '../store'
import { usd, toMicro } from '../format'

const edit = store.wizardEdit
const step = ref(0)
const busy = ref(false)
const error = ref('')
const STEPS = ['Hedef müşteri', 'Kaynak ve sorgu', 'Limitler ve özet']

const existingIcp = store.icps.find(i => i.id === edit?.icp_id) || store.icps[0]
const icp = reactive({
  id: existingIcp?.id || null as number | null,
  name: existingIcp?.name || 'Hedef müşteri',
  product: existingIcp?.product || '', website: existingIcp?.website || '',
  sectors: (existingIcp?.sectors || []).join(', '), geographies: (existingIcp?.geographies || []).join(', '),
  sizes: (existingIcp?.sizes || []).join(', '), roles: (existingIcp?.roles || []).join(', '),
  problems: (existingIcp?.problems || []).join(', '), competitors: (existingIcp?.competitors || []).join(', '),
  exclusions: (existingIcp?.exclusions || []).join(', '),
})
const c = reactive({
  name: edit?.name || 'Pilot kampanya',
  provider: edit?.provider || 'demo', enrich_provider: edit?.enrich_provider ?? '',
  signal_type: edit?.signal_type || 'content',
  queries: (edit?.queries || []).join('\n'),
  date_range_days: edit?.date_range_days || 30, result_limit: edit?.result_limit || 20, enrich_limit: edit?.enrich_limit ?? 5,
  budget: edit?.budget_run_micro ? String(edit.budget_run_micro / 1e6) : '0.50',
  schedule_daily: edit?.schedule_daily || false, schedule_hour: edit?.schedule_hour ?? 9,
})

const discovery = computed(() => store.sources.discovery)
const enrichers = computed(() => store.sources.enrichment)
const chosen = computed(() => discovery.value.find(s => s.key === c.provider))
const chosenEnrich = computed(() => enrichers.value.find(s => s.key === c.enrich_provider))
const queryList = computed(() => String(c.queries).split('\n').map((q: string) => q.trim()).filter(Boolean))
// Worst case: every query at the source's ceiling, plus every enrichment at its ceiling.
const maxSpend = computed(() => {
  const q = (chosen.value?.price?.ceiling_micro || 0) * queryList.value.length
  const e = c.enrich_provider ? (chosenEnrich.value?.price?.ceiling_micro || 0) * Number(c.enrich_limit) : 0
  return q + e
})
const capped = computed(() => Math.min(maxSpend.value, toMicro(c.budget)))
const isDemo = computed(() => !!chosen.value?.demo)

function suggestQueries() {
  const problems = String(icp.problems).split(',').map((s: string) => s.trim()).filter(Boolean)
  const geo = String(icp.geographies).split(',').map((s: string) => s.trim()).filter(Boolean)[0] || ''
  const lines = problems.slice(0, 3).map((p: string) => c.signal_type === 'hiring' ? `${p} uzmanı iş ilanı ${geo}`.trim() : `"${p}" çözüm arıyoruz ${geo}`.trim())
  if (lines.length) c.queries = lines.join('\n')
}

function validStep(): string {
  if (step.value === 0 && !icp.problems.trim()) return 'En az bir problem ifadesi girin; skor ICP uyumunu buradan ölçer.'
  if (step.value === 1 && !queryList.value.length) return 'En az bir sorgu girin.'
  if (step.value === 1 && chosen.value && !chosen.value.demo && chosen.value.state !== 'connected') return 'Seçili kaynak bağlı değil. Kaynaklar sayfasından anahtar ekleyin ya da Demo ile deneyin.'
  return ''
}
function next() { error.value = validStep(); if (!error.value) step.value++ }

async function save(run: boolean) {
  error.value = validStep()
  if (error.value) return
  busy.value = true
  try {
    const icpBody = { ...icp }
    const savedIcp = icp.id ? await api(`/leads/api/icps/${icp.id}`, { method: 'PUT', body: icpBody })
      : await api('/leads/api/icps', { method: 'POST', body: icpBody })
    const body = {
      name: c.name, icp_id: savedIcp.id, provider: c.provider, enrich_provider: c.enrich_provider,
      signal_type: c.signal_type, queries: queryList.value, date_range_days: Number(c.date_range_days),
      result_limit: Number(c.result_limit), enrich_limit: c.enrich_provider ? Number(c.enrich_limit) : 0,
      budget_run_micro: toMicro(c.budget), schedule_daily: c.schedule_daily, schedule_hour: Number(c.schedule_hour),
      status: run ? 'active' : (edit?.status || 'draft'),
    }
    const camp = edit ? await api(`/leads/api/campaigns/${edit.id}`, { method: 'PUT', body })
      : await api('/leads/api/campaigns', { method: 'POST', body })
    if (run) {
      await api(`/leads/api/campaigns/${camp.id}/run`, { method: 'POST' })
      toast('Tarama başladı. Sonuçlar Leadler sayfasına düşecek.')
    } else toast('Kampanya kaydedildi.')
    await Promise.all([loadIcps(), loadCampaigns(), loadOverview()])
    store.wizardOpen = false
    location.hash = run ? '#/campaigns' : location.hash
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally { busy.value = false }
}

function close() { store.wizardOpen = false }
const first = ref<HTMLElement | null>(null)
onMounted(() => first.value?.focus())
</script>

<template>
  <div class="scrim" @click="close" />
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="wiz-h" @keydown.esc="close">
    <div class="modal-h">
      <h2 id="wiz-h">{{ edit ? 'Kampanyayı düzenle' : 'Yeni kampanya' }}</h2>
      <button class="btn ghost sm" type="button" aria-label="Kapat" @click="close">✕</button>
    </div>
    <div class="modal-b">
      <ol class="steps">
        <li v-for="(s, i) in STEPS" :key="s" :aria-current="i === step ? 'step' : undefined" :class="{ done: i < step }">{{ i + 1 }}. {{ s }}</li>
      </ol>

      <div v-if="step === 0" class="form-grid">
        <div class="field wide"><label for="w-product">Ürün / hizmetiniz</label><input id="w-product" ref="first" v-model="icp.product" placeholder="Örn. depo yönetim yazılımı" /></div>
        <div class="field"><label for="w-sec">Sektörler</label><input id="w-sec" v-model="icp.sectors" placeholder="lojistik, e-ticaret" /><span class="hint">Virgülle ayırın.</span></div>
        <div class="field"><label for="w-geo">Ülke / şehir</label><input id="w-geo" v-model="icp.geographies" placeholder="Türkiye, İstanbul" /></div>
        <div class="field"><label for="w-size">Şirket büyüklüğü</label><input id="w-size" v-model="icp.sizes" placeholder="50-500 çalışan" /><span class="hint">Kaynaklar büyüklüğü nadiren verir; bilinmiyorsa puan verilmez.</span></div>
        <div class="field"><label for="w-roles">Karar verici rolleri</label><input id="w-roles" v-model="icp.roles" placeholder="Operasyon Müdürü, CTO" /></div>
        <div class="field wide"><label for="w-prob">Problem ifadeleri *</label><input id="w-prob" v-model="icp.problems" placeholder="stok takibi, depo hataları" /></div>
        <div class="field"><label for="w-comp">Rakipler</label><input id="w-comp" v-model="icp.competitors" placeholder="Rakip A, Rakip B" /></div>
        <div class="field"><label for="w-ex">Dışlama ölçütleri</label><input id="w-ex" v-model="icp.exclusions" placeholder="ajans, danışmanlık, işe alım firması" /><span class="hint">Eşleşen aday puanlanmadan elenir.</span></div>
      </div>

      <div v-else-if="step === 1" class="form-grid">
        <div class="field wide"><label for="w-name">Kampanya adı</label><input id="w-name" v-model="c.name" /></div>
        <div class="field"><label for="w-src">Keşif kaynağı</label>
          <select id="w-src" v-model="c.provider"><option v-for="s in discovery" :key="s.key" :value="s.key">{{ s.label }}{{ s.demo ? '' : s.state === 'connected' ? ' — bağlı' : ' — bağlı değil' }}</option></select>
          <span class="hint">{{ chosen?.data_note }}</span></div>
        <div class="field"><label for="w-sig">Sinyal tipi</label>
          <select id="w-sig" v-model="c.signal_type"><option value="content">Problemle ilgili herkese açık içerik</option><option value="hiring">İlgili işe alım ilanı</option></select></div>
        <div class="field wide"><label for="w-q">Sorgular (her satıra bir tane, en fazla 10)</label>
          <textarea id="w-q" v-model="c.queries" rows="4" placeholder='"stok takibi" çözüm arıyoruz' />
          <span class="hint"><button class="btn sm" type="button" @click="suggestQueries">Problem ifadelerinden öner</button> Her sorgu bir ücretli arama çağrısıdır (demo hariç).</span></div>
        <div class="field"><label for="w-days">Tarih aralığı (gün)</label><input id="w-days" v-model="c.date_range_days" type="number" min="1" max="365" /></div>
        <div class="field"><label for="w-en">E-posta zenginleştirme</label>
          <select id="w-en" v-model="c.enrich_provider"><option value="">Kapalı</option><option v-for="s in enrichers" :key="s.key" :value="s.key">{{ s.label }}{{ s.demo ? '' : s.state === 'connected' ? ' — bağlı' : ' — bağlı değil' }}</option></select>
          <span v-if="chosenEnrich" class="hint">{{ chosenEnrich.data_note }} Yalnızca uygun adaylara yapılır.</span></div>
      </div>

      <div v-else class="stack" style="gap:16px">
        <div class="form-grid">
          <div class="field"><label for="w-lim">Sonuç limiti</label><input id="w-lim" v-model="c.result_limit" type="number" min="1" max="100" /><span class="hint">İlk pilot için 20 önerilir.</span></div>
          <div class="field"><label for="w-elim">Enrichment limiti</label><input id="w-elim" v-model="c.enrich_limit" type="number" min="0" max="50" :disabled="!c.enrich_provider" /><span class="hint">İlk pilot için 5 önerilir.</span></div>
          <div class="field"><label for="w-bud">Koşu bütçesi (USD)</label><input id="w-bud" v-model="c.budget" inputmode="decimal" /><span class="hint">Sunucu bu sınırı ve günlük/aylık sınırları çağrı öncesi uygular.</span></div>
          <div class="field"><label for="w-sch">Günlük otomatik tarama</label>
            <div class="row"><input id="w-sch" v-model="c.schedule_daily" type="checkbox" /><span>Her gün saat</span>
              <input v-model="c.schedule_hour" class="input" type="number" min="0" max="23" style="width:72px" aria-label="Saat" :disabled="!c.schedule_daily" /><span class="muted small">(İstanbul)</span></div></div>
        </div>
        <div class="card" style="box-shadow:none">
          <h2>Başlatmadan önce</h2>
          <dl class="summary">
            <dt>Sağlayıcı</dt><dd>{{ chosen?.label }} <span v-if="isDemo" class="pill demo">Demo</span><span v-if="chosenEnrich"> + {{ chosenEnrich.label }}</span></dd>
            <dt>Veri kapsamı</dt><dd>{{ chosen?.data_note }} <span v-if="chosenEnrich">{{ chosenEnrich.data_note }}</span></dd>
            <dt>Çağrı başı tavan</dt><dd>{{ chosen?.price ? usd(chosen.price.ceiling_micro) : 'ücret bilinmiyor — çağrı engellenir' }}<span v-if="chosen?.price" class="muted small"> ({{ chosen.price.source }})</span></dd>
            <dt>Azami harcama</dt><dd><b>{{ isDemo && !c.enrich_provider ? '$0 (demo)' : usd(capped) }}</b> <span class="muted small">— {{ queryList.length }} sorgu × tavan{{ c.enrich_provider ? ` + ${c.enrich_limit} e-posta × tavan` : '' }}, koşu bütçesiyle sınırlı</span></dd>
            <dt>Kendi anahtarınız</dt><dd v-if="!isDemo" class="muted small">Çağrılar sağlayıcı hesabınızdaki krediden düşer; sağlayıcının kendi ücretlendirmesi geçerlidir.</dd><dd v-else class="muted small">Hiçbir sağlayıcıya veri gitmez.</dd>
          </dl>
        </div>
      </div>

      <p v-if="error" class="banner err" role="alert" style="margin:16px 0 0">{{ error }}</p>
    </div>
    <div class="modal-f">
      <button class="btn" type="button" :disabled="step === 0" @click="step--">Geri</button>
      <div class="row">
        <button v-if="step < 2" class="btn primary" type="button" @click="next">Devam</button>
        <template v-else>
          <button class="btn" type="button" :disabled="busy" @click="save(false)">Kaydet</button>
          <button class="btn primary" type="button" :disabled="busy" @click="save(true)">{{ busy ? 'Başlatılıyor…' : 'Kaydet ve tara' }}</button>
        </template>
      </div>
    </div>
  </div>
</template>
