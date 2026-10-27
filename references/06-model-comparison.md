# 06 — Model Comparison

## İlk adaylar

| Model | Rol |
|---|---|
| Midpoint/no-change | Referans |
| Simple momentum | Referans |
| Logistic regression | Yön olasılığı |
| Micro-Price | Kısa vadeli fiyat referansı |
| Small CatBoost | Nonlinear aday; VPS dışında eğitilir |

## Kurallar

- Aynı veri dönemi, aynı feature snapshot ve aynı maliyet varsayımı kullanılır.
- Kalibre edilmemiş skor olasılık değildir.
- 1 dakika ve 5 dakika ayrı hedeflerdir.
- Micro-Price’ın event-level çıktısı doğrudan 1/5 dk başarı oranı sayılmaz.
- Ensemble varsayılan değildir.
- Model seçimi validasyonda, final test yalnız bir kez.
- Sonuç negatifse strateji/model reddedilebilir; ayarlarla aynı testte kurtarılmaya çalışılmaz.

## Saklanacak manifest

- Model id.
- Training data window.
- Feature version.
- Label definition.
- Calibration method.
- Cost assumptions.
- Metrics: accuracy, Brier, log-loss, calibration bins, net expectancy, coverage, max drawdown, trades count.
