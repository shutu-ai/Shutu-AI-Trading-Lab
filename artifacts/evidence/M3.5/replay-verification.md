# M3.5 forward observation status

- mode: SYNTHETIC_REPLAY (evidence level SYNTHETIC_REPLAY)
- eligibility: **OFFLINE_HARNESS_PASS_WITH_SCOPE** — synthetic replay harness passed; scope is the test fixture only — never a real forward window
- real forward window: NOT_STARTED (source BLOCKED_DATA; 0/5 real days)
- S=INCONCLUSIVE · R=NOT_STARTED · paper=PAPER_NOT_RUN · broker writes=0
- cohort: m35-shadow-synthetic-replay-v1-s1 · duplicates=0 · held=0 · expired=1 · rejected=0
- scored: 25 (hit 5 / miss 9 / no_claim 11 / flat_close 0) — engineering stability counters only, never alpha
- no_broker_writes: True · account_environment: SYNTHETIC_REPLAY

SYNTHETIC_REPLAY outcomes are fixture proofs. They are not real forward trading days and cannot support E=PASS, alpha, or Live eligibility.
