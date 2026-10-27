# signal-desk-prediction

## Amaç

Binance BTCUSDT spot market data ile başlayan, paper-only kısa vadeli tahmin, karar, risk, paper execution, EOD ve taşınabilir deployment sistemi için teknik skill.

Bu skill çalışan bir trading bot değildir. Gerçek emir, gerçek para ve API trading key kullanımı kapsam dışıdır.

## V0 kararı

- Exchange: Binance.
- Product: BTCUSDT spot.
- Mode: paper-only.
- Execution: disabled.
- Scope: tüm sistem bileşenleri kurulacak; her stratejinin aynı anda başarılı olması hedeflenmez.
- Runtime dependency: Ruflo/ECC yok; bunlardan yalnız yöntem alınır.

## Öncelikli referanslar

1. `references/01-scope-and-mvp.md`
2. `references/02-binance-market-data-adapter.md`
3. `references/03-data-contract.md`
4. `references/04-config-contract.md`
5. `references/05-resource-retention-and-200gb-migration.md`
6. `references/06-strategy-catalog.md`
7. `references/07-model-comparison.md`
8. `references/08-risk-decision-engine.md`
9. `references/09-paper-fill-model.md`
10. `references/10-eod-report.md`
11. `references/11-observability-and-alarms.md`
12. `references/12-portable-deployment.md`
13. `references/13-external-methods.md`
14. `references/14-acceptance-gates.md`
15. `references/15-research-decision-policy.md`
16. [Time Machine](references/16-timemachine.md) — replay'den ayrı senaryo ve tarihsel kural araştırması.

## Geliştirme sırası

1. Config + schema validation.
2. Docker skeleton + health endpoint.
3. Binance BTCUSDT sample feed → raw event.
4. Local order book bootstrap/gap/resync.
5. Feature snapshot + causality checks.
6. Baseline prediction + S1 strategy signal.
7. Risk/Decision Engine + paper-fill modes.
8. EOD + alarms.
9. Clean-host deployment and restore test.
10. Model comparison + forward paper test.

## Cevap verirken dikkat

- Kurulum yapılmadıysa “tasarım güncellendi” de; “sistem çalışıyor” deme.
- Kârlılık iddiası üretme; yalnız test sonucu varsa konuş.
- Her yeni teknik karar araştırılmış kaynak ve `decision_log` girdisiyle eklenmelidir.
- Binance BTCUSDT V0’dır; futures/perpetual ayrı V1+ deneydir.

## Time Machine feature kararı — 2026-10-27

`timemachine` feature'ını replay modülünden ayrı geliştir. Monte Carlo senaryoları ile gerçek geçmiş kural testini ayrı tut; BTCUSDT spot paper-only, UTC, nedensellik ve maliyet sözleşmesini uygula. [Time Machine sözleşmesini](references/16-timemachine.md) oku. Şimdilik yalnız feature tasarımı kabul edildi; simülatör, şemalar ve testler uygulanmış değildir. VPS smoke testi bu feature'ı beklemez.

## Sürekli collector adayı

Sürekli toplama, reconnect veya resync işlerinde [collector sözleşmesini](references/17-continuous-collector.md) uygula. Yeni continuous modu yerel testlidir; VPS kabulü bekler. Compose varsayılanı idle kalır. Önce collector image/test, sonra 60 saniyelik sınırlı test; başarı ve kaynak ölçümü olmadan 24/7 kurulum yapma. Time Machine ve gerçek emir kapsamını değiştirme.

## Ham veri kabulü ve replay öncesi kontrol

Kaydedilmiş oturumun bütünlüğü için [raw-session audit sözleşmesini](references/18-data-audit.md) uygula. Önce tamamlanmış collector oturumunu session_id ile seç; sayım, şema, sıra ve dosya hash kontrollerini yap. Araç ham dosyaları değiştirmez. Büyük ham dosyayı listeye yükleyen mevcut replay okuyucusunu bu kontrolün yerine kullanma. Audit başarısı live/replay parity kabulü değildir.

## Tek işlemle taşınabilir kurulum

Kurulum veya yeniden kurulumda [INSTALLATION.md](INSTALLATION.md) ve [komut kataloğunu](docs/COMMANDS.md) uygula. install.sh mevcut checkout'u kullanır veya seçilmiş boş hedefe clone eder; deploy.sh aşamaları başarısızlıkta durdurur. Aktif config/veriyi koru, başka servisleri temizleme. Kurulum logu/manifest yerelde runtime/install altında kalır. Installer'ın yerel mock testini gerçek temiz-host, restore veya paper-ready kabulü sayma. Gerçek main merge için otomatik inceleme açık kullanıcı onayı isterse yalnız somut PR için onay al; ret işlemini ref güncellemesiyle aşma.
