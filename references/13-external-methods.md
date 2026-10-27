# 13 — External Methods Incorporated

## Day Trader Skill

Alınacaklar:

- Risk check before intent.
- Position sizing as minimum of risk, cash and max notional constraints.
- Exit plan before entry.

Uyarlama:

- ABD hisse varsayımları yerine BTC decimal lot/step.
- 15 dk stale price kabul edilmez.
- Daily loss ve risk reservation ayrılır.

## ECC

Alınacaklar:

- Latency-critical measurement: p50/p95/p99, stale data, queue depth.
- Verification loop.
- Docker patterns.
- Security principle: modelden bağımsız risk limits.

Runtime dependency değildir.

## Ruflo

Yalnız offline development/research coordination için opsiyonel. Runtime decision engine veya paper ledger’a bağlanmaz.

## Firmalardan alınan dersler

- Jane Street: live/replay ortak event-driven feature engine; aynı fiyatlı farklı olayları koru.
- Optiver: fill olmak iyi işlem anlamına gelmez; markout ölç.
- XTX/Optiver: büyük model kalıcı edge garantisi değildir; bozulma ve overfit izle.

## Araştırma kaynak ekleme kuralı

Her dış yöntem `references/15-research-decision-policy.md` uyarınca decision log girdisi ve kaynakla eklenir.

## Time Machine — kabul edilen ek feature

[Time Machine sözleşmesini](16-timemachine.md) uygula: mevcut replay'den ayrı senaryo simülasyonu ve tarihsel kural testi. Kaynak incelendi; BTC uyarlaması tasarım olarak kabul edildi, çalışan simülatör henüz yok.
