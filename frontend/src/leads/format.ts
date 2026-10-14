export const STATUS: Record<string, string> = {
  new: 'Yeni', review: 'İncelenecek', fit: 'Uygun', contacted: 'İletişime geçildi',
  replied: 'Yanıtlandı', won: 'Kazanıldı', dropped: 'Elendi',
}
export const STATUS_ORDER = ['new', 'review', 'fit', 'contacted', 'replied', 'won', 'dropped']

export const EMAIL_STATUS: Record<string, string> = {
  '': 'Aranmadı', found: 'Bulundu', verified: 'Doğrulandı', not_found: 'Bulunamadı', skipped: 'Atlandı',
}

export const RUN_STATUS: Record<string, string> = {
  queued: 'Sırada', running: 'Çalışıyor', succeeded: 'Tamamlandı', partial: 'Kısmen tamamlandı',
  failed: 'Başarısız', stopped: 'Durduruldu',
}

export const ISSUE: Record<string, string> = {
  timeout: 'Zaman aşımı', rate_limit: 'Hız sınırı', missing_credential: 'Eksik anahtar', empty: 'Boş sonuç',
  upstream: 'Sağlayıcı hatası', bad_response: 'Geçersiz yanıt', unknown_price: 'Ücret bilinmiyor',
  budget: 'Bütçe sınırı', interrupted: 'Yarıda kaldı', internal: 'İç hata',
}

/** micro-USD -> "$0.0160"; null/undefined -> "—". Small amounts keep four decimals. */
export function usd(micro: number | null | undefined): string {
  if (micro === null || micro === undefined) return '—'
  const v = micro / 1e6
  return '$' + (v !== 0 && Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2))
}

export function toMicro(dollars: string | number): number {
  const n = Number(String(dollars).replace(',', '.'))
  return Number.isFinite(n) && n > 0 ? Math.round(n * 1e6) : 0
}

export function day(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value.length <= 10 ? value + 'T00:00:00' : value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function when(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** The score's band in words, so it is never colour alone. */
export function band(score: number, qualified: boolean): { label: string, tone: string } {
  if (!qualified) return { label: 'Uygun değil', tone: 'muted' }
  if (score >= 70) return { label: 'Güçlü', tone: 'good' }
  if (score >= 45) return { label: 'Orta', tone: 'mid' }
  return { label: 'Zayıf', tone: 'low' }
}

export function safeUrl(url: string): string {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''
  } catch { return '' }
}
