# 09 — EOD Report

EOD her gün çalışır ve idempotent olmalıdır. Aynı gün tekrar çalıştırılırsa revision üretir.

## İnsan okunur rapor

- Data coverage.
- Gaps/stale periods.
- Number of predictions.
- Number of signals.
- Enter/blocked/wait counts.
- Paper trades.
- Gross/net paper PnL.
- Fees/slippage estimate.
- Stop/TP/time-stop outcomes.
- Markout summary.
- Model calibration.
- Strategy by regime.
- Top failure reasons.
- Alarms and halts.
- Next recommended research action.

## JSON sözleşmesi

`schemas/eod_report.schema.json` kullanılır.

## Midnight kuralları

- Gece yarısını aşan pozisyonlar önceki gün açılış kanıtıyla, kapanış günü sonucu ile ilişkilendirilir.
- Geç gelen fill correction EOD revision üretir.
- EOD final-test sonucunu model seçimine geri sızdırmaz.
