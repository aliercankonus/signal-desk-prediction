# 12 — External Methods

## Day Trader repository

Kullanılacak fikirler:
- Risk check.
- Position sizing.
- Exit plan.
- Order plan fingerprint.

Doğrudan alınmayacak:
- ABD hisse varsayımları.
- Tam hisse/sent hassasiyeti.
- 15 dakikalık freshness.
- Kriptoyu engelleyen kontroller.
- Broker akışı.

## ECC

Kullanılacak:
- Latency-critical systems ölçüm yaklaşımı.
- Verification loop.
- Docker patterns.
- LLM trading security’den modelden bağımsız risk limitleri.

Tam paket runtime dependency olmayacak.

## Ruflo

Opsiyonel geliştirme/araştırma koordinasyonu. Canlı Decision Engine veya ledger dependency değildir.

## Quant firmalarından dersler

- Canlı/replay ortak feature engine.
- Fiyat değişmedi diye olayları atlama.
- Dolum sonrası markout ölç.
- Timeout alttaki işi durdurmamış olabilir.
- Restart/snapshot/buffer güvenliği test edilir.
- Büyük model kârlılık garantisi değildir.

## Time Machine — kabul edilen ek feature

[Time Machine sözleşmesini](16-timemachine.md) uygula: mevcut replay'den ayrı senaryo simülasyonu ve tarihsel kural testi. Kaynak incelendi; BTC uyarlaması tasarım olarak kabul edildi, çalışan simülatör henüz yok.
