<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { store, loadSources, toast, type Source } from '../store'
import { usd, when } from '../format'

const keys = reactive<Record<string, string>>({})
const busy = ref('')
const tested = ref<Record<string, string>>({})

async function connect(s: Source) {
  const token = (keys[s.service] || '').trim()
  if (!token) return
  busy.value = s.service
  try {
    // Treg verifies the key against the provider's free probe, then stores it encrypted.
    await api('/connections/token', { method: 'POST', body: { provider: s.service, token } })
    keys[s.service] = ''
    toast(`${s.label}: anahtar doğrulandı ve kaydedildi.`)
    await loadSources()
  } catch (e) { toast(e instanceof Error ? e.message : String(e)) } finally { busy.value = '' }
}
async function test() {
  await loadSources()
  const now = new Date().toISOString()
  for (const s of [...store.sources.discovery, ...store.sources.enrichment]) tested.value[s.key] = now
  toast('Durum yenilendi (ücretsiz kontrol: anahtar, token ve fiyat).')
}
const STATE: Record<string, { label: string, tone: string }> = {
  connected: { label: 'Bağlı', tone: 'good' }, missing: { label: 'Eksik', tone: 'mid' },
  error: { label: 'Hatalı', tone: 'bad' }, demo: { label: 'Demo', tone: 'demo' },
}
onMounted(loadSources)
</script>

<template>
  <div class="page-h">
    <div><h1>Kaynaklar</h1><p>Kendi sağlayıcı anahtarlarınız. Anahtar Treg'de şifreli saklanır, çağrıda sunucu tarafında eklenir ve bir daha gösterilmez.</p></div>
    <button class="btn" type="button" @click="test">Durumu test et</button>
  </div>

  <div v-if="!store.sources.registry_token" class="banner warn" role="note">
    <div><b>Registry token yok.</b> Gerçek kaynaklar bu sunucunun kendi <code>/call/</code> yolunu kullanır. Sunucuyu <code>TREG_SINGLE_USER=1</code> ile başlatın (token otomatik yazılır) veya <code>TREG_LEADS_TOKEN</code> verin. Bu sırada Demo modu çalışır.</div>
  </div>
  <div class="banner" role="note"><div class="small">Self-host kurulum, treg.to'nun sağlayıcı hesaplarını veya ücretsiz bakiyesini taşımaz. Gerçek tarama için kendi anahtarınız gerekir ve <b>ücret sağlayıcı hesabınızdan düşer</b>. Ücreti doğrulanamayan çağrı sunucuda engellenir.</div></div>

  <template v-for="group in [{ title: 'Keşif', list: store.sources.discovery }, { title: 'E-posta zenginleştirme', list: store.sources.enrichment }]" :key="group.title">
    <h2 style="font-size:16px;margin:16px 0 8px">{{ group.title }}</h2>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr))">
      <article v-for="s in group.list" :key="s.key" class="card stack">
        <div class="row" style="justify-content:space-between"><b>{{ s.label }}</b><span class="pill" :class="STATE[s.state].tone"><span class="dot" aria-hidden="true" />{{ STATE[s.state].label }}</span></div>
        <p class="small muted" style="margin:0">{{ s.data_note }}</p>
        <dl class="summary" style="grid-template-columns:120px minmax(0,1fr)">
          <dt>Çağrı tavanı</dt><dd>{{ s.price ? usd(s.price.ceiling_micro) : 'bilinmiyor — engellenir' }}</dd>
          <template v-if="s.price && !s.demo"><dt>Fiyat kaynağı</dt><dd class="small">{{ s.price.source }}<span v-if="s.price.checked"> · kontrol {{ s.price.checked }}</span></dd></template>
          <dt>Son test</dt><dd>{{ when(tested[s.key] || s.last_checked) }}<span v-if="s.health && s.health !== 'unknown'" class="small muted"> · {{ s.health }}</span></dd>
        </dl>
        <ul v-if="s.missing.length" class="small" style="margin:0;padding-left:18px;color:var(--mid)"><li v-for="m in s.missing" :key="m">{{ m }}</li></ul>
        <form v-if="!s.demo" class="row" @submit.prevent="connect(s)">
          <label class="sr" :for="`k-${s.key}`">{{ s.label }} API anahtarı</label>
          <input :id="`k-${s.key}`" v-model="keys[s.service]" class="input" style="flex:1;min-width:160px" type="password" autocomplete="off" :placeholder="s.state === 'connected' ? 'Anahtarı değiştir…' : 'API anahtarı'" />
          <button class="btn sm primary" type="submit" :disabled="busy === s.service || !keys[s.service]">{{ busy === s.service ? 'Doğrulanıyor…' : 'Kaydet' }}</button>
        </form>
      </article>
    </div>
  </template>
</template>
