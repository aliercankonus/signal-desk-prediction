# Operator-reported bounded baseline diagnostic (development prefix)

## Provenance and scope

The following figures are **operator-reported**, not independently inspected host artifacts. The reported code commit is `c0d1c28c3dd66329f97e0b27d4df6e83d339eefa`. The input was a 90,000-record prefix spanning 1,541.010504 seconds. This inspected prefix is **development data**, not an untouched final test. No input/result hashes, resource measurements, or additional metrics were supplied here; none are inferred. No new run was performed for this record.

## Reported common-valid-time direction agreement

| Horizon | Common valid times | Momentum | Weighted-microprice proxy | Fixed S1 flow | Reported label directions |
| --- | ---: | ---: | ---: | ---: | --- |
| 60 seconds | 48 | 23/48 | 31/48 | 28/48 | up=30, down=18 |
| 300 seconds | 40 | 22/40 | 24/40 | 28/40 | up=35, down=5 |

An always-up comparison would match the reported up counts (30/48 and 35/40); this is **post-hoc descriptive context**, not a precommitted candidate, baseline win, selection rule, or evidence of predictive improvement. The 60- and 300-second labels overlap in time and are not independent trials. Coverage is short and selected to common valid times; the broader missing/invalid/pending distribution was not supplied. Economic results, fees, slippage, fills, risk-adjusted returns and live performance remain unknown. No strategy is selected or promoted from this diagnostic.

The proposed chronological split and untouched final test in `docs/research/s1_experiment_v1.json` have not been established by this prefix. Any future evaluation needs separately reviewed time boundaries, adequate data and a shared conservative paper fill/risk/ledger core. Do not rerun or overwrite existing operator evidence as a consequence of this record.
