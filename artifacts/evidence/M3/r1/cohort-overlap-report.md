# M3-R1 cohort overlap report (SYNTHETIC_ENGINEERING_ONLY)

declared_for_dataset: m3-r1-official-v1 (dataset_hash=4e68058d55d597a6f794589be3da44dc00783141bab33e72371bbb87e0b45080)

## Declared cohorts

| cohort | role | window | symbols |
|---|---|---|---|
| train | TRAIN | 2026-01-05..2026-01-09 | SYN-ETF |
| validation | VALIDATION | 2026-01-10..2026-01-14 | SYN-ETF |
| hist_oos | HIST_OOS (walk-forward region) | 2026-01-15..2026-01-23 | SYN-ETF |
| sealed_final | SEALED_FINAL (SEALED_NOT_MATERIALIZED — declared window only, no sample ids) | 2030-01-05..2030-07-04 | SYN-ETF-REAL (declared universe, not materialized) |
| forward | FORWARD | 2030-07-06..2031-01-05 | SYN-ETF-REAL (declared universe, not materialized) |

## Pairwise overlap matrix

# Cohort overlap report

| pair | time | symbols | event_ids | labels | available_ats | verdict |
|---|---|---|---|---|---|---|
| TRAIN#0 vs VALIDATION#1 | False | True | False | False | False | OK |
| TRAIN#0 vs HIST_OOS#2 | False | True | False | False | False | OK |
| TRAIN#0 vs SEALED_FINAL#3 | False | False | False | False | False | OK |
| TRAIN#0 vs FORWARD#4 | False | False | False | False | False | OK |
| VALIDATION#1 vs HIST_OOS#2 | False | True | False | False | False | OK |
| VALIDATION#1 vs SEALED_FINAL#3 | False | False | False | False | False | OK |
| VALIDATION#1 vs FORWARD#4 | False | False | False | False | False | OK |
| HIST_OOS#2 vs SEALED_FINAL#3 | False | False | False | False | False | OK |
| HIST_OOS#2 vs FORWARD#4 | False | False | False | False | False | OK |
| SEALED_FINAL#3 vs FORWARD#4 | False | True | False | False | False | OK |

**independent**: True

## Walk-forward folds over the HIST_OOS region (embargo=2d, f=0.6)

| fold | train | OOS |
|---|---|---|
| 1 | 2026-01-15..2026-01-16 (end embargoed) | 2026-01-18..2026-01-20 |
| 2 | 2026-01-17..2026-01-18 (end embargoed) | 2026-01-20..2026-01-22 |
| 3 | 2026-01-19..2026-01-20 (end embargoed) | 2026-01-22..2026-01-24 |

## Forward cohort discipline

- scoring before observation_available_at -> refused (CohortError)
- legal score at 2030-07-16 -> SCORED ; second score refused (polluted_for_future_selection=True)

## Independence verdict

independent = True
- sealed_final's sample-defining dimensions (time/events/labels) are disjoint from every historical cohort.
- symbol-universe overlap (sealed vs forward both declaring SYN-ETF-REAL) is a DISCLOSURE, not a leak — the asset universe is shared by declaration; sample IDs remain unmaterialized.
- Real market data remains BLOCKED_DATA: the sealed/forward cohorts above are declared windows only; materialization + sample IDs happen only when M1 data admission unblocks and M9 governance executes the pre-registered rule.

NOT alpha evidence; engineering boundary documentation only.
