# 09 — Paper Fill Model

Paper-fill gerçek fill değildir. Her fill kaydı mode, assumption, fee, slippage ve markout alanlarını taşır.

## Modlar

| Mod | Amaç |
|---|---|
| `conservative` | Kabul kapılarında ana mod; şüphede kötü senaryo |
| `neutral` | Normal analiz raporu; makul ama garantisiz varsayım |
| `optimistic` | Duyarlılık analizi; başarı iddiasında kullanılmaz |

## Conservative kurallar

- Marketable olmayan limit entry için yalnız touch yeterli değildir; yeterli karşı taraf trade volume veya queue proxy gerekir.
- Aynı interval içinde hem stop hem target görülürse stop-first.
- Spread crossing varsa taker fee + conservative slippage uygulanır.
- Partial fill desteklenir; unfilled qty açık risk olarak kalır veya expires_at sonrası cancel edilir.
- Veri stale/gap ise yeni fill yazılmaz.

## Neutral kurallar

- Touch + yeterli volume proxy ile kısmi fill kabul edilebilir.
- Stop/target ordering event sequence ile biliniyorsa sequence kullanılır; bilinmiyorsa conservative fallback.
- Slippage measured spread/volatility modelinden gelir.

## Optimistic kurallar

- Touch durumunda fill kabul edilebilir.
- Stop/target ambiguity target-first olamaz; en fazla neutral sequence veya mid assumption.
- Raporlarda “not for acceptance” etiketi zorunludur.

## Markout

Her fill için midpoint markout ölçülür:

- 1s
- 5s
- 30s
- 60s
- 300s

Amaç: fill sonrası fiyat davranışıyla adverse selection tanısı koymak. Markout net PnL yerine geçmez.

## Cancel race ve restart

- Cancel request sonrası geç fill gelebilir; fazla satış engellenir.
- Restart sonrası ledger reconcile bitmeden yeni ENTER yoktur.
- Partial fill cumulative qty ve remaining qty saklanır.
