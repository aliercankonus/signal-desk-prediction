# Decision: Time Machine ayrı araştırma feature'ı

## Status
accepted — feature sözleşmesi; implementation pending. 2026-10-27.

## Context
Kullanıcı Time Machine'in skill'lere eklenmesini ve mevcut replay'den ayrı feature olmasını istedi.

## Sources checked
2026-10-27 tarihinde Jakeschincariol/day-trader-skill commit 3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd altındaki trader-timemachine/SKILL.md, timemachine.py, tests/test_timemachine.py ve LICENSE incelendi. Sabit sürüm bağlantıları references/16-timemachine.md içinde. Kaynak testleri burada çalıştırılmadı.

## Decision
references/16-timemachine.md sözleşmesini kabul et. Sentetik senaryo ve gerçek geçmiş kural değerlendirmesini ayır. Kaynak bağımsız bar yöntemini referans olarak etiketle; block bootstrap henüz seçilmiş yöntem değildir. BTC 7/24 UTC, yalnız point-in-time veri, açık maliyetler ve stop gap'lerini uygula. Config/şemalar ve src/signal_desk/timemachine ileride uygulanacak; bugün runtime eklenmedi.

## Alternatives
Replay runner'ını simülasyona dönüştürmek reddedildi: farklı görevler. ABD seansı/Yahoo/ORB varsayımlarını değişmeden almak reddedildi. Monte Carlo oranını kalibre tahmin veya canlı risk vetosu yapmak reddedildi.

## Risks
Bağımsız bar örnekleme seri bağımlılığı bozabilir; 10.000 yol 10.000 bağımsız piyasa gözlemi değildir. 5m OHLC 60s hedefi veya L2 S1 geçmişini kanıtlamaz. Kaynak −1R stop varsayımı gap maliyetini gizler. Her biri yeni sözleşmede açık kısıt/test olarak işlendi.

## Tests added
Çalışan test eklenmedi; belge değişikliği. references/16-timemachine.md içindeki kabul senaryoları uygulama öncesi gereksinimdir. Bu güncelleme için referans/link, mevcut skill frontmatter ve uzak içerik bütünlüğü doğrulanır. VPS/Docker/simülasyon başarısı iddia edilmez.

## Rollback
Time Machine referansı ve bölümünü geri al; replay/risk/collector koduna dokunulmadığı için veri veya runtime migration gerekmez.
