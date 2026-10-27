# 06 — Strategy Catalog

## Kategori sırası

| Kategori | Strateji | Amaç | Aktivasyon |
|---|---|---|---|
| Baseline | S0 no-trade / midpoint / momentum | Referans | V0 zorunlu |
| Primary | S1 order-flow continuation | İlk işlem hipotezi | V0 primary |
| Variant | S1b cost gate | S1’in maliyet filtresi | S1 sonrası |
| Variant | S1c fixed stop/TP/time stop | Risk kontrollü S1 | S1b sonrası |
| Variant | S1d trailing stop A/B | Pozisyon yönetimi testi | S1c sonrası |
| Secondary | S2 breakout/retest | Momentum/kırılım hipotezi | V1 |
| Secondary | S3 VWAP mean reversion | Yatay piyasa dönüş hipotezi | V1 |

## V0 kuralı

V0’da tüm strateji arayüzleri bulunur; aktif paper karar sırası S0 + S1 ile başlar. S2/S3 kodlanabilir ama default ENTER üretmez; replay/analysis mode’da çalışabilir.

## Pozisyon yönetimi

- Yükseliş sürüyor diye sürekli kapat/aç yapılmaz.
- Mevcut pozisyon için HOLD varsayılan korunur.
- Stop güncelleme pozisyon kapatmaktan ayrı karardır: UPDATE_STOP.
- Long stop yalnız yukarı taşınır; aşağı indirilmez.
- Yeni tahmin azami tutma süresini sıfırlamaz.
- Yeniden giriş için kapanış doğrulaması, cooldown ve yeni signal gerekir.

## S1 order-flow continuation

Girdi adayları:

- Trade aggressor imbalance.
- Order book imbalance.
- Micro-price / weighted midpoint divergence.
- Spread and depth.
- Event intensity.
- Short-window returns.

Karar:

- Signal valid_until zorunlu.
- Expected move > fee + spread + slippage stress.
- Data quality OK.
- Risk budget OK.

## S2 breakout/retest

Öncelik V1. Basit breakout, breakout+retest ve breakout+flow confirmation ayrı ölçülür. Geri test beklemek net sonucu iyileştirmiyorsa kaldırılır.

## S3 VWAP mean reversion

Öncelik düşük. Sadece yatay/düşük trend rejiminde ve maliyeti aşabilecek sapma varsa paper analysis üretir.
