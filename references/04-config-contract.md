# 04 — Config Contract

Tüm runtime kararları merkezi `config.yaml` üzerinden yönetilir ve `schemas/config.schema.json` ile doğrulanır.

## Zorunlu config başlıkları

- `project`: name, version, mode, execution flag, config_version.
- `exchange`: Binance spot BTCUSDT endpoints, stream names, stale limits.
- `fees`: maker/taker bps, source, last_verified_ts, stale policy.
- `filters`: Binance exchangeInfo-derived symbol filters.
- `resources`: 100gb_2gb veya 200gb_2gb profile.
- `storage`: raw/features/ledger/models/reports/backups paths and codecs.
- `retention`: TTL days + pool GB + pin policies.
- `cache`: RAM budgets and ring-buffer sizes.
- `risk`: trade risk, daily loss, notional, cooldowns.
- `decision`: frequency, stale gates, idempotency settings.
- `paper_fill`: mode and assumptions.
- `strategies`: enabled strategy ids and sequence.
- `models`: active model/baseline ids.
- `alarms`: thresholds and actions.
- `eod`: timezone, cutoff, revision behavior.

## Config version policy

- Her risk/fee/fill/strategy/model değişikliği yeni `config_version` üretir.
- Açık pozisyon varken config değişirse mevcut pozisyon eski config ile izlenir; yeni girişler yeni config kullanır.
- Günlük zarar limiti düşürülürse hemen uygulanır.
- Günlük zarar limiti artırılırsa manual approval kaydı gerekir.

## Fee policy

- Maker/taker fee boşsa ENTER BLOCK.
- Fee verisi stale ise ENTER BLOCK veya açıkça tanımlı stress fee ile sadece analiz modu.
- Paper sonuçlarında fee source ve timestamp yazılır.

## Config startup gates

- `config.schema.json` valid.
- `execution_enabled=false`.
- `mode=paper`.
- `exchange.product_type=spot`.
- `exchange.symbol=BTCUSDT`.
- Fee fields non-null for paper trading.
- Storage paths writable.
- Resource profile host preflight ile uyumlu.
