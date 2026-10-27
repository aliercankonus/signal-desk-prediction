# 11 — Observability and Alarms

## Alarm seviyeleri

| Seviye | Anlam | Aksiyon |
|---|---|---|
| INFO | Normal bilgi | Logla |
| WARN | İncelenecek durum | EOD’ye ekle |
| BLOCK | Yeni ENTER yasak | Açık risk azaltma devam edebilir |
| HALT | Kritik | Yeni risk yok; maintenance/recovery |

## Otomatik aksiyonlar

| Durum | Alarm | Aksiyon |
|---|---|---|
| L2 stale | BLOCK | Yeni ENTER yok; resync |
| Trades stale | BLOCK | Yeni ENTER yok |
| Heartbeat missed | BLOCK | Reconnect/resync |
| Binance gap | BLOCK | Local book discard + bootstrap |
| Disk >85% | BLOCK | Yeni giriş yok |
| Disk >95% | HALT | Maintenance |
| Ledger write error | HALT | Tüm order intent durur |
| Model unavailable | WARN/BLOCK | Prediction unavailable; strategy ENTER yok |
| Fee stale/missing | BLOCK | Yeni ENTER yok |
| Recovery incomplete | BLOCK | Reconcile bitene kadar yeni giriş yok |
| RAM >95% | HALT | Worker restart/maintenance |
| Config invalid | HALT | Başlatma fail-closed |
| Schema validation error | HALT for writer | Bozuk event quarantine |

## Zorunlu metrikler

- decision_latency p50/p95/p99
- market_data_age_ms
- queue_depth
- raw_write_lag
- feature_compute_ms
- prediction_compute_ms
- risk_check_ms
- paper_fill_latency
- disk_pct
- rss_mb
- restart_count
- duplicate_event_count
- gap_count
- blocked_decision_count
- eod_revision_count

## Health endpoints

- `/health/live`: process alive.
- `/health/ready`: config + storage + market data + ledger + mode ready.
- `/health/paper`: paper-only and execution disabled confirmation.
- `/metrics`: Prometheus-compatible text or JSON metrics.
