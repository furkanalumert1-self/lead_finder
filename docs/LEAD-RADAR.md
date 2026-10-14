# Lead Radar — kişisel lead paneli (Treg üzerinde)

Lead Radar, şirketiniz için potansiyel müşterileri **kanıtlarıyla** bulmanızı, kurallı bir skorla
değerlendirmenizi ve takip etmenizi sağlayan tek kullanıcılı bir paneldir. Treg'in
(<https://github.com/superdesigndev/treg>, bu depo `273570d` commitinden türetildi) org/oturum,
şifreli anahtar saklama, `/call/` proxy'si ve veritabanı katmanını kullanır; ayrı bir auth sistemi,
mikroservis veya framework eklemez.

## Hızlı başlangıç (yerel, tek kullanıcı)

Gereksinimler: Linux/macOS ya da **Windows'ta WSL2 (Ubuntu)**; Node ≥ 22.12, npm, [uv](https://docs.astral.sh/uv/) ≥ 0.12.
Native Windows desteklenmez.

```bash
scripts/lead-radar.sh start
# → http://127.0.0.1:18790/leads
```

İlk çalıştırmada betik: paneli derler, `.env.leads.example`'dan `.env` üretir (şifreleme anahtarı ve
API token'ı **ekrana yazmadan** oluşturur, dosya izni 600), migration'ları uygular ve sunucuyu
yalnızca `127.0.0.1` üzerinde başlatır. `TREG_SINGLE_USER=1` sayesinde panel oturum açılmış gelir
(yalnızca yerel SQLite + loopback adreste etkinleşir).

| Komut | Ne yapar |
|---|---|
| `scripts/lead-radar.sh start` | kurulum + migration + sunucu (tek başlatma yolu) |
| `scripts/lead-radar.sh backup` | tutarlı DB kopyası + şifreleme anahtarlı `env` → `backups/<tarih>/` |
| `scripts/lead-radar.sh restore backups/<tarih>` | sunucu kapalıyken geri yükler, migration'ı çalıştırır |
| `scripts/lead-radar.sh build` | yalnızca arayüzü derler |

`scripts/dev-local.sh` ayrı bir geliştirme veritabanı kullanır; gerçek lead deposu (`./treg.db`) ile
karıştırmayın ve `reset` komutunu gerçek veri üzerinde çalıştırmayın. **`.env` dosyasını
yedekleyin:** `TREG_SECRET_KEY` olmadan kayıtlı sağlayıcı anahtarları çözülemez.

## Akış

ICP → kampanya → kaynak ve maliyet sınırı → küçük tarama → sinyal/uygunluk skoru → (isteğe bağlı)
en iyi uygun adaylara e-posta → inceleme → CSV → takip.

- **Genel Bakış:** son 7 günün uygun leadleri, inceleme kuyruğu, bu ayın gerçekleşen API ve LLM
  maliyeti (ayrı), uygun lead başına maliyet (payda sıfırsa “—”), son koşu, 7 günlük trend.
  Demo veriler bu sayılara katılmaz.
- **Kampanyalar:** 3 adımlı sihirbaz (Hedef müşteri / Kaynak ve sorgu / Limitler ve özet); başlatmadan
  önce sağlayıcı, veri kapsamı ve azami harcama gösterilir. Çalıştır / Durdur, koşu geçmişi ve
  sorunlar (zaman aşımı, hız sınırı, eksik anahtar, boş sonuç, bütçe, kısmi hata) ayrı ayrı.
- **Leadler:** filtre + arama + sıralama, sabit başlıklı tablo (mobilde kart), 440px detay çekmecesi:
  özet, “Neden şimdi?”, kanıt bağlantıları (yeni sekmede, `noopener`), skor gerekçesi, e-posta durumu,
  durum/not, izinli enrichment, şablondan kısa mesaj taslağı (**hiçbir şey gönderilmez**),
  iletişim hariç tutma, silme. CSV dışa aktarma (formül enjeksiyonuna karşı güvenli) ve içe aktarma,
  elle lead ekleme.
- **Kaynaklar:** bağlı / eksik / hatalı durumu, fiyat ve kaynağı, anahtar ekleme. Anahtar Treg'in
  mevcut `/connections/token` akışıyla sağlayıcıda doğrulanır, şifreli saklanır, bir daha gösterilmez.
- **Ayarlar:** ICP, günlük/aylık bütçe, cache süreleri, saklama süresi ve temizlik, hariç tutma
  listesi, demo verileri silme. Koyu tema tercihi kalıcıdır.

Durumlar: Yeni, İncelenecek, Uygun, İletişime geçildi, Yanıtlandı, Kazanıldı, Elendi. Yeni bir tarama
mevcut leade kanıt ekler, skoru yeniler; **durum ve notları değiştirmez**.

## Skor (0–100)

ICP uyumu 50 (problem ifadesi 20, sektör 10, coğrafya 10, rol 10) + sinyal gücü 30 (açık
ihtiyaç/işe alım ifadesi 15, rakip anılması 10, ek bağımsız kanıt +5/+10) + güncellik 20 (≤7 gün 20,
≤30 gün 14, ≤90 gün 7). Dışlama ölçütleri önce uygulanır ve adayı eler. Tanımlanmamış/bulunamayan
alan “bilinmiyor” sayılır ve puan vermez. **Kanıtsız aday uygun lead sayılmaz** (uygun = kanıt var ve
ICP uyumu ≥ 20). Skor kuraldır; “satın alma ihtimali %” değildir. Normalizasyon, dedup ve skor LLM
kullanmaz; şu an hiçbir yerde LLM çağrısı yoktur (LLM maliyeti bu yüzden $0 görünür).

## Kaynaklar, maliyet ve gizlilik

| Kaynak | Uç | Ücret (katalogdan) | Giden veri |
|---|---|---|---|
| Demo | — | $0 | hiçbir şey; şirketler `.example` alan adlı uydurmadır |
| Tavily web araması | `tavily.web.search` (basic) | tavan 2 kredi × $0.008 = **$0.016**/sorgu; gerçekleşen yanıttaki `usage.credits` | arama sorgusu → tavily.com |
| Hunter e-posta bulucu | `hunter.people.email.find` | 1 kredi × $0.0245 = **$0.0245**, yalnızca bulunursa | kişi adı + şirket domaini → hunter.io |

Fiyatlar Treg kataloğundaki satırlardan (`src/treg/catalog/tavily.yaml`, `hunter.yaml`, `fx.yaml`)
hesaplanır; planınız farklıysa `PUT /leads/api/settings` ile `prices_micro` (çağrı başı, mikro-USD) girilebilir — arayüzde henüz yok.
Fiyatı belirlenemeyen çağrı engellenir. **Kendi anahtarınız kullanıldığından ücret sağlayıcı
hesabınızdan düşer**; Treg bakiyesinden düşmez. Self-host kurulum treg.to'nun sağlayıcı hesaplarını
veya ücretsiz bakiyesini taşımaz.

Bütçe koruması sunucudadır: koşu/gün/ay sınırları, aynı takımın eşzamanlı çağrıları için atomik
rezervasyon, çağrı öncesi tavan kontrolü ve sonradan mutabakat. Sınır girilmemişse ücretli çağrı
yapılmaz. Zaman aşımında rezerv “belirsiz” olarak sayılmaya devam eder (sıfırlanmaz). En fazla 2
kontrollü tekrar, yalnızca 429 ve kurulamayan bağlantı için.

Gizli anahtarlar yalnızca sunucuda; sağlayıcı hata gövdesindeki anahtarlar Treg tarafından maskelenir.
Kaynaklardan gelen metin yalnızca veri olarak saklanır, komut olarak yürütülmez; yalnızca kayıtlı
adaptörler çalışır. Hariç tutma listesindeki kişi/domain/e-posta enrichment'e gönderilmez. AB/BK
kişilerine ulaşmak için hukuki dayanak gerekir; liste ve abonelikten çıkma kayıtları önce gelir.

## Günlük zamanlama

Kampanyada “Günlük otomatik tarama” açılırsa sunucu her gün belirtilen saatte (Europe/Istanbul) bir
kez çalıştırır. Aynı gün ikinci kez başlamaz (veritabanında `(kampanya, gün)` benzersizdir);
yeniden başlatmada yarıda kalan koşu “başarısız / yarıda kaldı” olarak kapanır, tekrar başlatılmaz.
Tek uvicorn worker ile çalıştırın. `TREG_LEADS_SCHEDULER=0` zamanlamayı tamamen kapatır.
Zamanlama canlı bir LLM ajanı çalıştırmaz; Run düğmesiyle aynı deterministik akıştır.

## Vercel'de çalıştırma (vercel.app linki)

Vercel'de uygulama **sunucusuz modda** çalışır: tarama, “Çalıştır”a basıldığı istekte biter (en
fazla ~5 dk); günlük zamanlama Vercel Cron ile her gün 06:00 UTC'de (İstanbul 09:00) bir kez tetiklenir;
veri Postgres'te durur. Repo hazır: `app.py` (giriş noktası), `vercel.json` (`/` → `/leads`, cron),
`.vercelignore`, `requirements.txt` ve derlenmiş panel (`src/treg/web/dashboard`).

1. **Proje:** Vercel → Add New → Project → `lead_finder` reposu, dal `claude/zen-darwin-82ycf9`.
   **Application/Framework Preset: FastAPI.** Root Directory: `./` (boş). Build/Install komutlarını
   değiştirmeyin.
2. **Veritabanı:** Projede Storage → **Neon (Postgres)** ekleyin ve projeye bağlayın. Vercel
   `DATABASE_URL` vb. değişkenleri ekler.
3. **Ortam değişkenleri** (Settings → Environment Variables, Production):

   | Değişken | Değer |
   |---|---|
   | `TREG_DATABASE_URL` | Neon'un `DATABASE_URL` değeri (`postgres://…?sslmode=require` olduğu gibi kalabilir) |
   | `TREG_SECRET_KEY` | `uv run python -m treg keygen` çıktısı — **saklayın**, kaybolursa kayıtlı anahtarlar çözülemez |
   | `TREG_PUBLIC_URL` | `https://<proje-adınız>.vercel.app` |
   | `TREG_LEADS_SERVERLESS` | `1` |
   | `TREG_FIXED_LOGIN_CODES` | `e-postanız=<giriş kodunun sha256'sı>` (aşağıda) |
   | `TREG_API_TOKEN` | uzun rastgele bir değer |
   | `CRON_SECRET` | uzun rastgele bir değer (Vercel Cron bunu otomatik gönderir) |
   | `TREG_TELEMETRY` / `DO_NOT_TRACK` | `0` / `1` |
   | `TREG_LEADS_TOKEN` | 6. adımdan sonra eklenecek |

   Giriş kodu: e-posta göndermeden yalnızca sizin bildiğiniz kodla giriş yapılır. Uzun bir kod seçip
   özetini alın: `printf %s 'UZUN-GİZLİ-KOD' | sha256sum` → `siz@sirket.com=<64 karakter>`.
   Kodun kendisini değil yalnızca özetini Vercel'e girin.
4. **Tabloları oluşturun** (bir kez ve her güncellemeden sonra, kendi bilgisayarınızdan):
   `TREG_DATABASE_URL='<Neon adresi>' TREG_SECRET_KEY='<aynı anahtar>' uv run python -m treg upgrade`
   — Uygulama, veritabanı geride kalırsa açılmayı reddeder.
5. **Deploy** edin; `https://<proje>.vercel.app` açılınca `/app` üzerinden e-postanız + giriş kodunuzla
   girin ve bir takım oluşturun. Lead Radar: `https://<proje>.vercel.app/leads`.
6. **Gerçek kaynaklar ve cron için token:** `/app` → takım → API anahtarları → yeni anahtar; değeri
   `TREG_LEADS_TOKEN` olarak ekleyip yeniden deploy edin. Sonra Kaynaklar sayfasından Tavily/Hunter
   anahtarınızı girin.

Notlar: Panel ve API girişsiz erişime kapalıdır (401); ancak adres herkese açıktır, giriş kodunu
paylaşmayın. Upstream Treg'in tanıtım sayfaları da aynı alan adında açık kalır. Hobby planında cron
günde bir kez ve ±1 saat sapmayla çalışır; kampanyanın saati 09 veya daha erken olmalıdır. Arayüzü
değiştirdiğinizde `scripts/vercel-prepare.sh` çalıştırıp çıkan dosyaları commit edin. Yerel
`backup/restore` betiği yalnızca SQLite içindir; Neon'un kendi yedek/geri yükleme (branch) özelliğini
kullanın.

## Uzaktan kişisel kullanım (yalnızca gerekirse)

Varsayılan yerel kullanımdır. Kendi sunucunuza taşıyacaksanız (public yayın yapmadan):

1. Özel bir VM + HTTPS önünde ters proxy (Caddy/nginx); güvenlik duvarında yalnızca 443.
2. `TREG_PUBLIC_URL=https://<alan-adınız>`, `TREG_SINGLE_USER` **kaldırın** (zaten yalnızca loopback'te
   çalışır), gerçek oturum açma: e-posta OTP için SMTP ayarları ya da GitHub/Google OAuth
   (`.env.example` ve `docs/context/architecture/auth-secrets.md`).
3. `TREG_HOST=127.0.0.1` kalsın; dış erişim yalnızca proxy üzerinden.
4. Kalıcı disk ve `scripts/lead-radar.sh backup` için zamanlanmış görev; bir yedeği ayrı makinede
   `restore` ile **deneyerek** doğrulayın. Postgres kullanırsanız `pg_dump` + `TREG_SECRET_KEY` yedeği.
5. Bu adımlar sizin onayınız olmadan uygulanmaz; bu depo hiçbir şeyi otomatik yayınlamaz.

## Testler ve doğrulama

```bash
uv run --frozen python -m pytest -q tests/test_leads.py      # dedup, skor, takım ayrımı, hariç tutma,
                                                             # eşzamanlı bütçe, timeout/kısmi hata, CSV, zamanlama
uv run --with pytest-xdist pytest -n auto -q                 # tüm suite
uv run lint-imports                                          # katman sözleşmeleri
npm --prefix frontend run check                              # typecheck
```

Mimari ayrıntı: [docs/context/architecture/lead-radar.md](context/architecture/lead-radar.md).
SaaS'a geçiş ön koşulları: [docs/lead-radar-saas.md](lead-radar-saas.md).
