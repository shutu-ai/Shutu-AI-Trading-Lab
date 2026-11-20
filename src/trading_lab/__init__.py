"""Shutu AI Trading Lab platform package.

M2 scope adds risk (independent engine), oms (durable intents, state
machine, single-writer egress) and a fake-only broker plane. No network
code exists anywhere; real Alpaca behavior stays BROKER_BEHAVIOR_UNVERIFIED.
"""

__version__ = "0.2.0"
