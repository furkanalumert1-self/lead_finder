# Lead Radar — SaaS ön koşulları (şimdi uygulanmıyor)

Bu panel şu an **tek kullanıcı, şirket içi** kullanım içindir. Başkalarına hizmet olarak sunmadan önce:

1. **Yazılı lisans yetkisi.** Treg LICENSE ek şartı, kodun (değiştirilmiş hali dahil) üçüncü kişilere
   hosted/managed/embedded hizmet olarak sunulmasını önceden yazılı izne bağlar: jason@superdesign.dev.
   Lisans ve atıflar kaldırılmaz; bağımsız yeniden yazım otomatik muafiyet sayılmaz.
2. **Sağlayıcı izinleri.** Tavily, Hunter vb. sağlayıcıların yeniden satış ve veri kullanım
   koşulları; müşteri başına kendi anahtarı mı, sizin anahtarınız mı.
3. **Müşteri izolasyonu.** Org kapsamı zaten zorunlu; çok kiracılı ortamda ayrıca sızma testleri,
   kiracı başına kota ve kötüye kullanım sınırları.
4. **Veri politikaları.** KVKK/GDPR hukuki dayanak, aydınlatma, saklama süresi, silme talepleri,
   hariç tutma ve abonelikten çıkma süreçleri, alt işleyen listesi.
5. **Operasyon.** Postgres, yedek/geri yükleme tatbikatı, izleme, olay müdahalesi, çoklu worker için
   zamanlayıcıyı ayrı tek süreçte çalıştırma.
6. **Sonra billing.** Abonelik ve faturalama ancak yukarıdakilerden sonra.
