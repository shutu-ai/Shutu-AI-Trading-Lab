"""Alpaca offline probe: show what happens without real credentials.
Uses DUMMY keys against the paper endpoint (no real account, no keys created).
Expected: HTTP 401 from paper-api.alpaca.markets -> RuntimeError, proving that
even dry_run=True requires valid credentials (it calls /v2/clock, /v2/positions,
/v2/account before planning orders).
"""
import sys, os

repo = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, repo)
os.environ.pop("APCA_API_KEY", None)
os.environ.pop("APCA_API_SECRET", None)

from src.trading.alpaca_manager import AlpacaManager, AlpacaAccount

dummy = AlpacaAccount(
    name="dummy", api_key="DUMMYKEY123", api_secret="DUMMYSECRET123",
    base_url="https://paper-api.alpaca.markets",
)
mgr = AlpacaManager([dummy])

print("case 1: create_alpaca_account_from_env with NO credentials in env")
try:
    from src.trading.alpaca_manager import create_alpaca_account_from_env
    create_alpaca_account_from_env()
    print("  UNEXPECTED: no error")
except Exception as e:
    print(f"  {type(e).__name__}: {e}")

print("case 2: AlpacaManager.execute_portfolio_rebalance(dry_run=True) with dummy keys")
try:
    plan = mgr.execute_portfolio_rebalance({"AAPL": 0.5, "MSFT": 0.5}, dry_run=True)
    print(f"  UNEXPECTED success: {plan}")
except Exception as e:
    print(f"  {type(e).__name__}: {e}")
