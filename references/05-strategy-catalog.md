# 05 — Strategy Catalog

Stratejiler doğru kategorilere ayrılmıştır. Her strateji ayrı ön kayıt, test ve sonuç ister.

## Kategori A — Baseline / No-trade

### S0: No-trade and simple baseline
Amaç, sistemin işlem açmadan piyasa hareketlerini ve model referanslarını ölçmesidir.

- No-trade baseline.
- Midpoint/no-change.
- Simple momentum.
- Cost-only gate.

## Kategori B — Primary Alpha Candidate

### S1: Order-flow continuation
İlk ana strateji.

Giriş adayı:
- Trade pressure aynı yönde.
- L2 book imbalance/depth change destekliyor.
- Spread ve fee sonrası beklenen hareket maliyeti karşılıyor.
- Data quality healthy.
- Aynı sinyal reset olmadan tekrar giriş yok.

Çıkış:
- Fixed stop.
- Take profit.
- Time stop.
- Signal invalidation.
- Risk or data HALT.

### S1b: S1 + cost gate
S1’in maliyet filtresi sertleştirilmiş varyantıdır.

### S1c: S1 + fixed stop/TP
İlk paper kabul varyantı. Trailing kapalı.

### S1d: S1 + trailing stop A/B
Sabit stop’a karşı ayrı deneydir. Varsayılan değildir.

Trailing kuralları:
- Long stop yalnız yukarı taşınabilir.
- UPDATE_STOP pozisyonu kapatmaz.
- Yeni tahmin holding süresini sıfırlamaz.
- Pending stop update ile confirmed stop ayrı tutulur.
- Stop aşağı indirilemez; gevşetme manuel config change sayılır.

## Kategori C — Structural Price Action

### S2: Breakout and retest
Önceki aralık kırılımı + geri test + order-flow doğrulaması.

Kullanım:
- S1’den sonra.
- Geri test filtresinin net expectancy’yi artırıp artırmadığı ölçülür.
- Daha az trade tek başına başarı değildir.

## Kategori D — Mean Reversion Candidate

### S3: VWAP mean reversion
Yatay/düşük trend koşullarında VWAP sapmasından dönüş adayı.

Kullanım:
- Düşük öncelikli keşif.
- Maliyet sonrası hareket büyüklüğü kritik.
- Trend günlerinde otomatik çalıştırılmaz.

## Strateji sırası

1. S0 baseline.
2. S1 order-flow continuation.
3. S1b cost gate.
4. S1c fixed stop/TP.
5. S1d trailing A/B.
6. S2 breakout/retest.
7. S3 VWAP mean reversion.
