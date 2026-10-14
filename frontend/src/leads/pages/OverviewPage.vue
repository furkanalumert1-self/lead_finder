<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { store, loadOverview } from '../store'
import { usd, when, RUN_STATUS, ISSUE } from '../format'

const o = computed(() => store.overview)
const maxLeads = computed(() => Math.max(1, ...(o.value?.trend || []).map((t: any) => t.leads)))
const hasRealData = computed(() => (o.value?.real_leads || 0) > 0)
const shortDay = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString('tr-TR', { weekday: 'short' })
function newCampaign() { store.wizardEdit = null; store.wizardOpen = true }
onMounted(loadOverview)
</script>

<template>
  <div class="page-h">
    <div>
      <h1>Genel Bakış</h1>
      <p>Son 7 günün uygun leadleri, inceleme kuyruğu ve sağlayıcı harcaması.</p>
    </div>
  </div>

  <div v-if="o && !hasRealData && o.demo_leads" class="banner demo" role="note">
    <span class="pill demo">Demo</span>
    <div>Şu ana kadarki leadlerin hepsi <b>demo veri</b> ({{ o.demo_leads }} adet). Demo sonuçları aşağıdaki sayılara katılmaz ve gerçek başarı sayılmaz.</div>
  </div>

  <div v-if="o && !o.real_leads && !o.demo_leads && !store.campaigns.length" class="card empty">
    <h2>İlk kampanyanı oluştur</h2>
    <p>Hedef müşteriyi tanımla, bir kaynak seç ve küçük bir taramayla başla. Anahtar bağlı değilse demo veriyle akışı deneyebilirsin.</p>
    <button class="btn primary" type="button" @click="newCampaign">İlk kampanyanı oluştur</button>
  </div>

  <template v-if="o">
    <div class="grid cols-4" style="margin-bottom:16px">
      <div class="card kpi"><div class="k-label">Yeni uygun lead (7 gün)</div><div class="k-value">{{ o.new_fit_7d }}</div><div class="k-sub">Kanıtlı ve ICP uyumu ≥ 20</div></div>
      <div class="card kpi"><div class="k-label">İnceleme bekleyen</div><div class="k-value">{{ o.pending_review }}</div><div class="k-sub"><a href="#/leads">Leadlere git</a></div></div>
      <div class="card kpi"><div class="k-label">Gerçekleşen maliyet (bu ay)</div><div class="k-value">{{ usd(o.month_api_cost_micro) }}</div>
        <div class="k-sub">API {{ usd(o.month_api_cost_micro) }} · LLM {{ usd(o.month_llm_cost_micro) }}<span v-if="o.month_uncertain_micro"> · belirsiz {{ usd(o.month_uncertain_micro) }}</span></div></div>
      <div class="card kpi"><div class="k-label">Uygun lead başına maliyet</div><div class="k-value">{{ usd(o.cost_per_fit_micro) }}</div><div class="k-sub">Bu ayın gerçek (demo dışı) uygun leadleri</div></div>
    </div>

    <div class="grid cols-2">
      <section class="card" aria-labelledby="trend-h">
        <div class="row" style="justify-content:space-between">
          <h2 id="trend-h">Son 7 gün</h2>
          <div class="legend"><span><i style="background:var(--accent)" />Yeni lead</span><span><i style="background:var(--good)" />Uygun</span></div>
        </div>
        <div class="trend" role="img" :aria-label="'Son 7 gün: ' + o.trend.map((t: any) => `${t.day} ${t.leads} lead, ${t.qualified} uygun`).join('; ')">
          <div v-for="t in o.trend" :key="t.day" class="bar">
            <small>{{ t.leads || '' }}</small>
            <span class="b" :style="{ height: (t.leads / maxLeads * 100 - t.qualified / maxLeads * 100) + '%' }" />
            <span class="q" :style="{ height: (t.qualified / maxLeads * 100) + '%' }" />
            <small>{{ shortDay(t.day) }}</small>
          </div>
        </div>
        <p v-if="!o.trend.some((t: any) => t.leads)" class="muted small">Bu hafta henüz gerçek lead yok; grafik yalnızca gerçek verileri gösterir.</p>
      </section>

      <section class="card" aria-labelledby="run-h">
        <h2 id="run-h">En son koşu</h2>
        <p v-if="!o.last_run" class="muted">Henüz koşu yok.</p>
        <dl v-else class="summary">
          <dt>Durum</dt><dd><span class="pill" :class="{ good: o.last_run.status === 'succeeded', mid: o.last_run.status === 'partial', bad: o.last_run.status === 'failed' }">{{ RUN_STATUS[o.last_run.status] }}</span>
            <span v-if="o.last_run.demo" class="pill demo" style="margin-left:6px">Demo</span></dd>
          <dt>Zaman</dt><dd>{{ when(o.last_run.finished_at || o.last_run.started_at || o.last_run.created_at) }}</dd>
          <dt>Aday / uygun / yeni</dt><dd>{{ o.last_run.candidates }} / {{ o.last_run.qualified }} / {{ o.last_run.new_leads }}</dd>
          <dt>E-posta zenginleştirme</dt><dd>{{ o.last_run.enriched }}</dd>
          <dt>Maliyet</dt><dd>API {{ usd(o.last_run.api_cost_micro) }} · LLM {{ usd(o.last_run.llm_cost_micro) }}</dd>
          <template v-if="o.last_run.issues.length">
            <dt>Sorunlar</dt>
            <dd><ul class="list"><li v-for="(i, n) in o.last_run.issues.slice(0, 4)" :key="n"><span><b>{{ ISSUE[i.kind] || i.kind }}:</b> {{ i.message }}</span></li></ul></dd>
          </template>
        </dl>
      </section>
    </div>
  </template>
</template>
