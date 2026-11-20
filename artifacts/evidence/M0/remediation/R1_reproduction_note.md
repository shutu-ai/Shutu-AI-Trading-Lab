# R1 reproduction (2026-11-20): clean isolated venv, git worktree at cd194ca
# command: pip install -e ".[dev]" (build isolation on, proxy per env policy)
# result:  INSTALL_EXIT=1 — setuptools rejects license="Proprietary" (invalid SPDX string form)
#          same root cause as CI run 44755037633 Ubuntu Install failure
# fix on latest HEAD: 5656dc5 license="LicenseRef-Proprietary"; verified green by run 44755451594 (both matrices)

