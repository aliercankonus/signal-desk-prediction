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
