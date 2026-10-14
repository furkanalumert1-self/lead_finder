# Lead Radar — ilerleme (≤30 satır)

Taban: superdesigndev/treg `273570dc` (14 Eki 2026). Ayrıntı: docs/LEAD-RADAR.md.

**Tamam:** lead tabloları + migration 0073; saf kurallar (dedup, skor, suppression, CSV); adaptörler
(Demo, Tavily keşif, Hunter e-posta — Treg `/call/` üzerinden kendi anahtar); sunucu tarafı bütçe
(atomik rezervasyon, mutabakat, belirsiz timeout); cache; koşu motoru; İstanbul saatli günlük
zamanlayıcı; `/leads` Vue paneli (5 sayfa, sihirbaz, çekmece, koyu tema, mobil); tek başlatma +
yedek/geri yükleme betiği; takım silmede lead tabloları temizleniyor.

**Değişen dosyalar:** src/treg/{models.py, domain/leads/, application/leads/, routers/leads.py,
alembic/versions/0073_lead_radar.py, bootstrap.py, api.py, config.py, __main__.py (TREG_HOST),
domain/governance/teams.py}; frontend/{leads.html, src/leads/, vite.config.ts}; scripts/lead-radar.sh;
.env.leads.example; tests/test_leads.py (+ manifest/snapshot güncellemeleri); docs.

**Doğrulandı:** tests/test_leads.py (11), tüm suite, lint-imports, vue-tsc, vitest, build-dashboard;
demo akışı 1440px ve 390px'te Playwright ile (konsol hatası yok, yatay taşma yok); yeniden başlatma +
yedekten geri yükleme sonrası not/durum ve şifreli anahtar korunuyor; anahtarsız Tavily çağrısı
"Eksik anahtar" verip rezervi serbest bırakıyor.

**Eksik / kullanıcıdan beklenen:** şirket/ürün, ICP, ülke/dil, roller, problem, bütçe (koşu/aylık);
Tavily (ve isterse Hunter) anahtarı. Gerçek pilot (≤20 aday, ≤5 enrichment) anahtar + bütçe gelince.
Fiyat geçersiz kılma yalnızca API'de (arayüz yok). LLM kullanılmıyor (taslak şablon).

**Sonraki iş:** anahtarla küçük gerçek pilot → sonuç kalitesine göre sorgu ayarı → günlük zamanlamayı
aç; gerekirse Kaynaklar'a fiyat geçersiz kılma alanı; ikinci keşif kaynağı (işe alım ilanları).
