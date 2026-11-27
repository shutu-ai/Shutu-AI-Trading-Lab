#!/usr/bin/env python3
"""Business MVP V0.1 — one-command offline replay.

    python scripts/run_business_mvp.py --mode replay --fixture demo \
        --output-dir <run-dir>

Only the offline replay mode exists in V0.1; every other mode fails
closed. No network, no keys, no real broker, no paid LLM:
    SYNTHETIC_OFFLINE_ONLY · AI_PROVIDER=MOCK/RULE ·
    EXECUTION_BACKEND=FAKE_BROKER / MOCK_ONLY
A business demo PASS is a product-integration result — never strategy
effectiveness, never formal stage acceptance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_lab.business.config import BusinessConfig, load_config  # noqa: E402
from trading_lab.business.replay import REPLAY_VERSION, run_replay  # noqa: E402

DEFAULT_CONFIG = REPO / "configs/business_mvp_demo.yaml"
DEFAULT_PROTOCOL = REPO / "configs/business_mvp_protocol.yaml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_business_mvp",
        description="Business MVP V0.1 offline replay (SYNTHETIC_OFFLINE_ONLY)")
    parser.add_argument("--mode", default="replay",
                        help="only 'replay' is authorized in V0.1")
    parser.add_argument("--fixture", default="demo",
                        help="only the built-in 'demo' fixture exists in V0.1")
    parser.add_argument("--output-dir", required=True,
                        help="run output directory (created if missing)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="pinned business config YAML")
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL),
                        help="demo evaluation protocol YAML")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode != "replay":
        print(f"REFUSED: mode {args.mode!r} is not authorized in V0.1 "
              f"(only 'replay'); other modes fail closed.", file=sys.stderr)
        return 2
    if args.fixture != "demo":
        print(f"REFUSED: fixture {args.fixture!r} does not exist in V0.1 "
              f"(only 'demo').", file=sys.stderr)
        return 2

    config = load_config(Path(args.config))
    if config.mode != "replay":
        print("REFUSED: config mode is not 'replay'.", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    artifacts = run_replay(
        config=config,
        protocol_path=Path(args.protocol),
        output_dir=output_dir,
        command=f"python scripts/run_business_mvp.py --mode replay "
                f"--fixture demo --output-dir {output_dir}",
    )
    print(f"[{REPLAY_VERSION}] run complete")
    print(f"  run_id      : {artifacts.run_id}")
    print(f"  run_digest  : {artifacts.run_digest}")
    print(f"  summary     : {artifacts.summary_path}")
    print(f"  report      : {artifacts.output_dir / 'report.html'}")
    print("  labels      : SYNTHETIC_OFFLINE_ONLY · AI_PROVIDER=MOCK/RULE · "
          "EXECUTION_BACKEND=FAKE_BROKER/MOCK_ONLY")
    print("  honesty     : BUSINESS_DEMO_ONLY — not strategy effectiveness, "
          "not formal stage acceptance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
