# 10 — Observability and Alarms

## Alarm seviyeleri

| Seviye | Anlam | Aksiyon |
|---|---|---|
| INFO | Normal bilgi | Logla |
| WARN | İncelenecek durum | EOD’ye ekle |
| BLOCK | Yeni ENTER yasak | Açık risk azaltma devam edebilir |
| HALT | Kritik | Yeni risk yok, servis maintenance/recovery |

## Otomatik aksiyonlar

| Durum | Alarm | Aksiyon |
|---|---|---|
| L2 stale | BLOCK | Yeni ENTER yok |
| Trades stale | BLOCK | Yeni ENTER yok |
| Heartbeat missed | BLOCK | Reconnect/resync |
| Disk >85% | BLOCK | Yeni giriş yok |
| Disk >95% | HALT | Maintenance |
| Ledger write error | HALT | Tüm order intent durur |
| Model unavailable | WARN/BLOCK | Prediction unavailable; strategy ENTER yok |
| Fee stale | BLOCK | Stress fee veya yeni ENTER yok |
| Recovery incomplete | BLOCK | Reconcile bitene kadar yeni giriş yok |
| RAM >95% | HALT | Worker restart/maintenance |
| Config invalid | HALT | Başlatma fail-closed |

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
