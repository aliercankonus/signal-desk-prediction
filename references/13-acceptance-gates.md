# 13 — Acceptance Gates

## Kapılar

| Gate | Çıktı |
|---|---|
| G0 | Scope/config/project state |
| G1 | Docker skeleton |
| G2 | Binance BTCUSDT collector |
| G3 | Storage/replay/checkpoint |
| G4 | Feature + baseline + paper core |
| G5 | Model comparison |
| G6 | Forward paper |
| G7 | Portable clean-host restore |
| G8 | 200GB migration drill |

## Fault tests

- Engine `FLAT` iken kill → recover flat.
- `PENDING_SEND` sonrası kill → duplicate intent yok.
- Partial fill + cancel race → filled qty korunur.
- L2 stale → ENTER BLOCK.
- Trade stale → ENTER BLOCK.
- Fee stale → ENTER BLOCK veya stress fee.
- Ledger write failure → HALT.
- Disk 85% → ENTER BLOCK.
- Disk 95% → HALT.
- Stop + TP aynı interval → conservative stop-first.
- Snapshot öncesi buffer isteği → açık hata; sıfır doldurma yok.
- EOD tekrar çalıştırma → revision, duplicate sonuç yok.
- 200GB migration → hash/manifest korunur.

## Başarı ayrımları

Ayrı ayrı raporla:

1. Veri akıyor.
2. Replay doğru.
3. Tahmin üretiliyor.
4. Risk/decision çalışıyor.
5. Paper fill tutarlı.
6. Ekonomik sonuç pozitif.
7. Taşınabilir restore geçti.

Bunlardan biri diğerinin kanıtı değildir.
