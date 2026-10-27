# Time Machine — ayrı araştırma feature'ı

## Durum ve sınır
2026-10-27: Kullanıcı tarafından kabul edilmiş feature sözleşmesi; uygulama ve sonuçlar henüz yok.
Feature adı: `timemachine`. Kayıtlı market event → feature üreten `replay` modülünden ayrı tut.
Time Machine'i tahmin modeli, yeni strateji, canlı emir yolu veya paper executor olarak sunma.
Binance BTCUSDT spot long/flat paper-only kapsamını koru. VPS smoke testinin ön şartı yapma.

## Araştırılmış kaynak ve alınan yöntem
İncelenen kaynak: Jakeschincariol/day-trader-skill, commit
`3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, kontrol tarihi 2026-10-27.
- [Skill](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/SKILL.md)
- [Kod](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/timemachine.py)
- [Testler](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/tests/test_timemachine.py)
- [MIT lisansı](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/LICENSE)

Kaynak uygulama geçmiş seansların OHLC/önceki kapanış oranlarını saat dilimine göre
örnekler; varsayılan 10.000 senaryo ve seed=19 kullanır. Aynı mumda stop/TP
dokunursa stop-first uygular. Gerçek geçmiş kural testini ayrı raporlar.
Tarihsel kural desteği ORB ile sınırlıdır; her stratejinin backtest'i değildir.
Kaynak testleri incelendi, burada çalıştırılmadı. Kaynak kod kopyalanmadı/kurulmadı.
İleride kod veya önemli metin kopyalanırsa MIT telif ve izin metnini koru.

## Bizim uyarlama kararları
- ABD seans/kapanış/Yahoo varsayımlarını taşıma; doğrulanmış Binance verisi ve UTC kullan.
  60 gün geçmiş hedefi ve 10.000 senaryo/seed=19 başlangıç araştırma ayarlarıdır,
  yeterli örneklem veya doğruluk garantisi değildir.
- İlk bar senaryosunu 5 dakikalık bar ve en az bir tam bar ufkuyla sınırla.
  60 saniye hedefi için 1 dakikalık, daha kısa hedef için yeterli olay verisi gerekir;
  5 dakikalık OHLC'den 60 saniyelik sonuç çıkarma.
- 24 saat sınırını zorunlu çıkış sayma. Planın `horizon_seconds` ve
  `time_stop_seconds` değerlerini uygula; gerçek süre sonu fill'i ile değerlemeyi ayır.
- Havuzu yalnız `as_of` anından önce erişilebilir, kapanmış barlardan kur.
  Açık bar, gelecek düzeltme, deney final penceresi ve düşük kalite/gap aralıklarını dışla.
  Her pencerede expected/observed bar sayısı ve kullanılabilir geçmiş kapsamını kaydet.
- Kaynağın bağımsız bar örneklemesini `independent_bar_reference_v1` referansı say;
  seri bağımlılığı ve volatilite kümelenmesini koruduğunu varsayma.
  Block-bootstrap yalnız ayrı yöntem adayıdır; yöntem/blok uzunluğu ve seçim aralığını
  validation üzerinde önceden kaydetmeden varsayılanlaştırma.
- Eksik fee, slippage, veri minimumları veya zaman bütçesiyle sayısal sonuç üretme:
  `unavailable` ve neden döndür. Minimum kapsamı deneyden önce config'te sabitle;
  evrensel "20 gün yeterli" veya "10.000 örnek bağımsız kanıttır" sonucu çıkarma.
- Aynı bar stop ve hedefe dokunursa conservative stop-first uygula.
  Long stop altına gap açılışında çıkış fiyatını stop'a sabitleme:
  bar modelinde min(stop, open) üzerinden olumsuz kayma uygula.
  OHLC'den gerçek kuyruk sırası, spread veya partial fill kanıtı çıkarma.
- Net PnL = qty × (exit_fill − entry_fill) − entry_fee − exit_fee.
  Net R = net PnL / başlangıç plan riski; risk = qty × (entry_reference − stop_reference).
  Fee ve kaymayı sürümlü maliyet varsayımı olarak raporla; kaybı −1R ile sınırlama.
  Stop/TP olasılığı ekonomik avantaj değildir; süre sonunda açık kalanları gizleme.
- Canlı risk/ledger/intent değiştirme. Offline veya ayrı sınırlı araştırma worker'ında çalıştır;
  2 GB toplam profil içinde açık CPU/RAM/süre sınırı olmadan VPS'de başlatma.

## İki ayrı çıktı
1. `scenario_simulation`: planın sentetik yollarında target-first / stop-first /
   horizon-open oranı; toplam 1; tüm senaryolar için net R ve PnL dağılımı,
   terminal midpoint/bar fiyatı bantlarını fill veya pozisyon getirisi bandı diye sunma.
   Monte Carlo örnekleme hatasını piyasa model belirsizliğinden ayır.
2. `historical_rule_test`: sabit strateji kuralı ve nedensel giriş üretimi ile gerçek
   geçmiş sonuçları; işlem sayısı, coverage, maliyet ve zaman bölmeleri.
   S1 order-flow kuralı için gerekli L2/trade özellikleri yoksa mumdan sonuç uydurma;
   `unsupported` döndür. Senaryo planını geçmiş her güne aynı fiyatla yapıştırma.
   Planın tarihsel kuralı tanımlı değilse bu kanalı atla ve nedeni yaz.

Bu iki kanalı birleştirip tek "başarı olasılığı" verme; uyuşmazlığı görünür tut.
Veri sayısı, tarih aralığı, seed, algoritma ve maliyet sürümlerini her rapora koy.
Model seçimi yalnız validation'da; final-test verisini simülasyon havuzuna sızdırma.

## Planlanan modül ve sözleşmeler
Henüz oluşturulmuş veya doğrulanmış dosyalar olarak gösterme:
- `src/signal_desk/timemachine/`: replay'den ayrı feature.
- `schemas/timemachine_plan.schema.json`, `schemas/timemachine_result.schema.json`.
- Merkezi config altında `timemachine`: enabled=false, method_version,
  seed, simulations, bar_interval_seconds, horizon_seconds, lookback_days,
  min_history_bars, min_history_days, max_runtime_seconds, max_memory_mb ve costs_version.
  Parametreleri config.schema ile doğrulamadan çalışma moduna bağlama.
- Plan: plan_id, symbol, product_type, side, as_of, entry_reference, stop_reference,
  target_reference, quantity, horizon/time-stop, strategy/rule_version ve costs_version.
- Sonuç: run_id, status/reason, plan/config/data hashes, kaynak commit,
  available_at/as_of, kullanılan veri aralığı/kalitesi, seed/simulations/method,
  ayrı scenario_simulation ve historical_rule_test, kaynak tüketimi.
- Rapor: `reports/timemachine/<run_id>.json`; aynı girdiler, yöntem ve seed ile
  deterministik içerik. created_at/duration gibi runtime alanlarını içerik hash'inden ayır.

## Kabul senaryoları — uygulamada eklenecek, henüz geçmedi
- Sabit veri/plan/config/seed aynı sonuç; değişen girdi yeni fingerprint.
- as_of sonrası veriyi eklemek sonucu değiştirmez; açık/gap barlar dışlanır.
- Stop-first; stop altına gap'te kayıp −1R'den kötü olabilir; çift yönlü fee/slippage.
- target + stop + open = 1; horizon-open PnL ve maliyeti toplamdan çıkarılmaz.
- 5 dakikalık bar ile 60 saniyelik istek reddedilir.
- Yetersiz veri/maliyet veya desteklenmeyen tarihsel kural açık status üretir.
- Yöntem duyarlılığı ve gerçek geçmiş sonuçları ayrı raporlanır.
- Süre/RAM limiti işi gerçekten durdurur; collector/ledger etkilenmez.
- Replay çıktıları ve mevcut risk/decision testleri değişmeden geçer.

Önce bu sözleşme ve kaynak kaydını koru; sonra şemalar/config, saf simülasyon çekirdeği,
fixture testleri, tarihsel kural adapter'ı ve offline rapor sırasıyla uygula.
