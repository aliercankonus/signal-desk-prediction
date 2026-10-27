# 04 — Resource, Retention and 200 GB Migration

## Initial profile: 100 GB disk / 2 GB RAM

| Area | Budget |
|---|---:|
| Raw Zstd events | 30 GB |
| Feature/label data | 12 GB |
| Prediction/paper/eod logs | 5 GB |
| Models | 2 GB |
| Backups | 5 GB |
| Temp/logs | 6 GB |
| OS/Docker | 15 GB |
| Emergency reserve | 20 GB |
| Spare | 5 GB |

## 200 GB profile

The 200 GB profile aims to better support 60 days of raw replay and reduce deletion pressure on research windows.

| Area | 100 GB | 200 GB |
|---|---:|---:|
| Raw Zstd events | 30 GB | 90 GB |
| Feature/labels | 12 GB | 24 GB |
| Prediction/paper/EOD | 5 GB | 10 GB |
| Models | 2 GB | 4 GB |
| Local backups | 5 GB | 15 GB |
| Temp/logs | 6 GB | 10 GB |
| OS/Docker | 15 GB | 20 GB |
| Emergency reserve | 20 GB | 25 GB |
| Spare | 5 GB | 2 GB |

## Migration triggers

Recommend migration to 200 GB when:

- Compressed raw data exceeds 1 GB/day for three consecutive days.
- 60-day raw replay is required.
- Disk usage above 70% delays new experiments.
- Feature/label pins reduce raw retention below seven days.

## Disk actions

| Threshold | Action |
| --- | --- |
| >70% | Do not start large research jobs; produce a retention report |
| >85% | ENTER BLOCK; no new entries |
| >90% | Maintenance mode; verify cleanup/backup |
| >95% | HALT; stop risky writers other than the collector, or make them read-only |

## RAM rules

- No Redis initially.
- Total live cache at most 64 MiB.
- Engine container target RSS ≤512 MiB.
- API ≤192 MiB.
- One maintenance worker ≤384 MiB.
- Heavy training runs outside the VPS.

## Migration acceptance

1. Create a backup.
2. Verify the new disk space.
3. Expand or restore Docker volumes without changing their paths.
4. Run `docker compose up -d --wait`.
5. Verify raw/feature/model manifest hashes.
6. Verify EOD and paper ledger idempotency.
