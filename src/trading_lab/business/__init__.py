"""Business MVP vertical slice (V0.1, SYNTHETIC_OFFLINE_ONLY).

Integration layer: consumes the existing data / backtest / security /
risk / oms / brokers planes through their public surfaces. It is the TOP
consumer — no restricted plane may import this package (enforced by
scripts/check_architecture.py). Not a formal stage: passing this MVP does
not constitute strategy effectiveness or formal stage acceptance.
"""
