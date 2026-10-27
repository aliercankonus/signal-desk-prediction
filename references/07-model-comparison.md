# 07 — Model Comparison

## İlk adaylar

| Model | Rol |
|---|---|
| No-change / midpoint | Referans |
| Simple momentum | Referans |
| Logistic regression | Yön olasılığı |
| Micro-Price | Kısa vadeli fiyat referansı |
| Small CatBoost | Nonlinear aday; VPS dışında eğitilir |

## Kurallar

- Aynı veri dönemi, aynı feature snapshot ve aynı maliyet varsayımı kullanılır.
- Kalibre edilmemiş skor olasılık değildir.
- 1 dakika ve 5 dakika ayrı hedeflerdir.
- Event-level Micro-Price çıktısı doğrudan 1/5 dk başarı oranı sayılmaz.
- Ensemble varsayılan değildir.
- Model seçimi validasyonda, final test yalnız bir kez yapılır.
- Sonuç negatifse strateji/model reddedilebilir; aynı final testte ayar değiştirerek kurtarılmaz.

## Veri bölme

Önerilen araştırma penceresi 60 gündür; 100 GB profil tam raw replay için yeterli olmayabilir. Feature/label seti daha uzun tutulabilir, ancak fill/replay iddiaları raw detay desteği ister.

## Saklanacak manifest

`model_manifest.schema.json` zorunludur:

- Model id/version.
- Training/validation/final windows.
- Feature version.
- Label definition.
- Calibration method.
- Cost assumptions.
- Metrics: accuracy, Brier, log-loss, calibration bins, net expectancy, coverage, max drawdown, trades count.
- Artifact hash.
