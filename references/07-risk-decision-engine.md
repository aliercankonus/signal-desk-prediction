# 07 — Risk and Decision Engine

## Kararlar

- `ENTER`: Yeni paper pozisyon açma niyeti.
- `HOLD`: Mevcut pozisyonu koru.
- `UPDATE_STOP`: Pozisyonu kapatmadan stop korumasını güncelle.
- `EXIT`: Açık pozisyonu kapatma/azaltma isteği.
- `WAIT`: Fırsat yok.
- `BLOCK`: Veri, risk, config veya sistem sorunu nedeniyle yeni giriş engeli.
- `HALT`: Kritik sistem durumu; yeni risk alınmaz.

## Durumlar

Mode, position state, order intent state ve risk latch ayrı saklanır.

Position:
- `FLAT`
- `OPENING`
- `OPEN`
- `CLOSING`
- `UNCERTAIN`
- `RECOVERING`

Order intent:
- `PLANNED`
- `RISK_RESERVED`
- `PENDING_SEND`
- `ACKED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCEL_REQUESTED`
- `CANCELLED`
- `REJECTED`
- `UNKNOWN`

## Öncelik sırası

1. Ledger write failure → BLOCK/HALT.
2. Recovery/reconciliation incomplete → BLOCK.
3. Open risk reduction EXIT/UPDATE_STOP.
4. Daily loss latch.
5. Data freshness gate.
6. Fee/cost gate.
7. Strategy ENTER.
8. HOLD/WAIT.

## Risk varsayılanları

- Risk/trade: 0.25% equity.
- Daily loss: 1.0% start-of-day equity.
- Max notional: 10% equity.
- Max open positions: 1.
- Re-entry cooldown: 60s.
- After stop cooldown: 300s.

Bunlar paper başlangıç parametreleridir; optimum değildir.

## Günlük zarar davranışı

Daily loss tetiklenirse:
- Yeni ENTER BLOCK.
- Bekleyen girişler iptal edilir.
- Açık miktar için EXIT istenir.
- Veri bayatsa çıkış tamamlanmış gösterilmez; state `UNCERTAIN/RECOVERING` kalır.

## İdempotency

Order intent id, şu alanlardan türetilmelidir:

- strategy_id
- signal_id
- config_version
- portfolio_version
- feature_snapshot_id
- decision_time
- side
- intended_qty
- stop/tp/time_stop plan hash

Aynı intent belirsiz kaldıysa yeni kimlikle tekrar gönderme; reconcile et.
