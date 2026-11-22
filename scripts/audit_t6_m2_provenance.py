"""T6.2 static provenance audit for the three regenerated M2 concurrency
logs — auditors written against the files' REAL shapes (inspected from
the git objects themselves; the first draft assumed JSON and was wrong).

READ-ONLY over git objects and the working tree: no re-runs, no writes
to evidence, no history rewriting. For each file, BOTH versions (old =
a3bf463, new = 2a60864) are checked for the same protocol invariants:

- A5/A2: 50 race rounds, unique monotone coids/round ids, exactly one
  claimed=True per round, winner == the claiming pid, distinct worker
  pids, SUMMARY count line consistent;
- A2 additionally: 5 crash rounds with a crash-claimed survivor check,
  SUMMARY race_rounds=50 crash_rounds=5 violations=0;
- A6: header comment + 50 pipe-format round records + SUMMARY line;
  rounds 1..50 monotone, single claimant per round, winner in pids,
  distinct pids, SUMMARY violations=0 with both pids represented;
- cross-version: run-identity-masked structure IDENTICAL (pids, winners,
  claimed orientations, coid serials, interpreter versions neutralized)
  -> the new file is a fresh valid run of the SAME protocol, and the
  only differences are run-identity facts.

Exit 0 = every invariant holds on both versions.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OLD = "a3bf463"
NEW = "2a60864"

A5 = "artifacts/evidence/M2/a5-true-process-race/process_concurrent_50.log"
A6 = "artifacts/evidence/M2/a6-strict-process-proof/barrier_50_rounds.jsonl"
A2 = ("artifacts/evidence/M2/final-send-claim/"
      "a2-quantitative-close/process_50_rounds.log")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          check=True).stdout


def blob_sha(rev: str, path: str) -> str:
    out = git("ls-tree", rev, "--", path).strip()
    return out.split()[2] if out else "(absent)"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _single_claim(claimed: list[bool], pids: list[int], winner: int,
                  label: str, problems: list[str]) -> None:
    if sum(claimed) != 1:
        problems.append(f"{label}: claimed={claimed} != single winner")
        return
    for pid, claimed_flag in zip(pids, claimed):
        if claimed_flag and pid != winner:
            problems.append(
                f"{label}: winner {winner} is not the claimant {pid}")


def audit_a5(text: str, label: str) -> list[str]:
    problems: list[str] = []
    header = text.splitlines()[0]
    if not header.startswith("# A5-T1 50 rounds"):
        problems.append(f"{label}: header changed: {header!r}")
    pids_m = re.search(r"workerA pid=(\d+) workerB pid=(\d+) "
                       r"distinct_pids=(\w+)", text)
    if not pids_m or pids_m.group(3) != "True" or \
            pids_m.group(1) == pids_m.group(2):
        problems.append(f"{label}: distinct worker pids invariant broken")
        return problems
    worker_pids = (int(pids_m.group(1)), int(pids_m.group(2)))
    rounds = re.findall(
        r"^round=(\d+) coid=(\S+) pidA=(\d+) pidB=(\d+) "
        r"claimed=\[(True|False), (True|False)\] winner_pid=(\d+)",
        text, re.M)
    if len(rounds) != 50:
        problems.append(f"{label}: race rounds={len(rounds)} != 50")
    coids_seen: set[str] = set()
    for idx, (num, coid, pa, pb, ca, cb, winner) in enumerate(rounds,
                                                              start=1):
        if int(num) != idx:
            problems.append(f"{label}: round numbering break at {num}")
        if coid in coids_seen:
            problems.append(f"{label}: duplicate coid {coid}")
        coids_seen.add(coid)
        _single_claim([ca == "True", cb == "True"],
                      [int(pa), int(pb)], int(winner), f"{label} r{num}",
                      problems)
    summary = re.search(
        r"^SUMMARY rounds=(\d+) violations=(\d+) "
        r"distinct_winner_pids=\[(\d+), (\d+)\]", text, re.M)
    if not summary:
        problems.append(f"{label}: SUMMARY line missing/changed")
    else:
        if int(summary.group(1)) != 50 or int(summary.group(2)) != 0:
            problems.append(f"{label}: SUMMARY counts wrong: {summary.group(0)}")
        winners = {int(summary.group(3)), int(summary.group(4))}
        if winners != set(worker_pids):
            problems.append(f"{label}: SUMMARY winner pids != worker pids")
    return problems


def audit_a6(text: str, label: str) -> list[str]:
    """A6 claimed vectors are ARRIVAL-ordered (not pid-positional): the
    winner is the pid holding the single True claim, but which array
    slot corresponds to which pid varies per round (verified empirically
    against both versions: r1 winner=pids[1] with claimed[0]=True, r2
    winner=pids[0] with claimed[0]=True). The statically provable
    invariants are therefore: exactly one claimant; winner is one of the
    two pids; pids distinct and stable across rounds; both pids win
    (SUMMARY liveness); violations=0 attests the generator's own
    winner-claimant cross-check. The positional binding itself is
    attested ONLY by that counter — recorded here as a declared limit."""
    problems: list[str] = []
    lines = text.splitlines()
    if len(lines) != 52:
        problems.append(f"{label}: line count {len(lines)} != 52 "
                        "(header + 50 rounds + SUMMARY)")
    if not lines[0].startswith("# A6-T1 50 rounds"):
        problems.append(f"{label}: header changed: {lines[0]!r}")
    worker_pids: set[int] = set()
    winners_seen: set[int] = set()
    seen_rounds: list[int] = []
    for line in lines[1:51]:
        m = re.match(
            r"^round=(\d+) pids=\[(\d+), (\d+)\] "
            r"claimed=\[(True|False), (True|False)\] winner_pid=(\d+)$",
            line)
        if not m:
            problems.append(f"{label}: malformed round line: {line!r}")
            continue
        num, pa, pb = int(m.group(1)), int(m.group(2)), int(m.group(3))
        claimed = [m.group(4) == "True", m.group(5) == "True"]
        winner = int(m.group(6))
        seen_rounds.append(num)
        worker_pids.update({pa, pb})
        if sum(claimed) != 1:
            problems.append(f"{label} r{num}: claimed={claimed} != single "
                            "claimant")
        if winner not in (pa, pb):
            problems.append(f"{label} r{num}: winner {winner} is not one "
                            "of the round pids")
        winners_seen.add(winner)
    if seen_rounds != list(range(1, 51)):
        problems.append(f"{label}: rounds not exactly 1..50 monotone")
    if len(worker_pids) != 2:
        problems.append(f"{label}: worker pids not distinct/stable: "
                        f"{worker_pids}")
    if winners_seen != worker_pids:
        problems.append(f"{label}: liveness broken — winners {winners_seen} "
                        f"!= both workers {worker_pids}")
    summary = lines[51] if len(lines) > 51 else ""
    sm = re.match(r"^SUMMARY rounds=50 violations=0 "
                  r"distinct_winner_pids=\[(\d+), (\d+)\]$", summary)
    if not sm:
        problems.append(f"{label}: SUMMARY line missing/changed: {summary!r}")
    else:
        winners = {int(sm.group(1)), int(sm.group(2))}
        if winners != worker_pids:
            problems.append(f"{label}: SUMMARY pids != round pids "
                            f"{worker_pids}")
    return problems


def audit_a2(text: str, label: str) -> list[str]:
    problems: list[str] = []
    lines = text.splitlines()
    if not lines[0].startswith("# A4-3 two-real-process claim race"):
        problems.append(f"{label}: header changed: {lines[0]!r}")
    pids_m = re.search(r"workerA pid=(\d+) workerB pid=(\d+)", text)
    if not pids_m or pids_m.group(1) == pids_m.group(2):
        problems.append(f"{label}: worker pids invariant broken")
        return problems
    race = re.findall(
        r"^round=(\d+) coid=(\S+) pidA=(\d+) pidB=(\d+) "
        r"claimed=\[(True|False), (True|False)\] db_state=(\S+) "
        r"winner_pid=(\d+) ok=(\w+)", text, re.M)
    if len(race) != 50:
        problems.append(f"{label}: race rounds={len(race)} != 50")
    coids_seen: set[str] = set()
    for idx, (num, coid, pa, pb, ca, cb, _db, winner, ok) in enumerate(
            race, start=1):
        if int(num) != idx:
            problems.append(f"{label}: round numbering break at {num}")
        if coid in coids_seen:
            problems.append(f"{label}: duplicate coid {coid}")
        coids_seen.add(coid)
        if ok != "True":
            problems.append(f"{label}: round {num} ok={ok}")
        _single_claim([ca == "True", cb == "True"],
                      [int(pa), int(pb)], int(winner), f"{label} r{num}",
                      problems)
    crash = re.findall(
        r"^crash_round=(\d+) coid=(\S+) crash_claimed=(\w+) "
        r"survivor_claimed=(\w+) ok=(\w+)", text, re.M)
    if len(crash) != 5:
        problems.append(f"{label}: crash rounds={len(crash)} != 5")
    for num, coid, crash_claimed, survivor, ok in crash:
        if crash_claimed != "True" or survivor != "False" or ok != "True":
            problems.append(
                f"{label}: crash round {num} state "
                f"crash={crash_claimed} survivor={survivor} ok={ok}")
    summary = re.search(
        r"^SUMMARY race_rounds=(\d+) crash_rounds=(\d+) violations=(\d+)",
        text, re.M)
    if not summary or (int(summary.group(1)), int(summary.group(2)),
                       int(summary.group(3))) != (50, 5, 0):
        problems.append(f"{label}: SUMMARY counts wrong/missing")
    return problems


_MASK_RULES = [
    (re.compile(r"pid[AB]?=\d+"), "pid=N"),
    (re.compile(r"winner_pid=\d+"), "winner_pid=N"),
    (re.compile(r"claimed=\[(True|False), (True|False)\]"),
     "claimed=[C,C]"),
    (re.compile(r"pids=\[\d+, \d+\]"), "pids=[N,N]"),
    (re.compile(r"distinct_winner_pids=\[\d+, \d+\]"),
     "distinct_winner_pids=[N,N]"),
    (re.compile(r"=(\d{6,})"), "=N"),
    (re.compile(r"interpreter [\d.]+"), "interpreter V"),
]


def masked_structure(text: str) -> str:
    out = text
    for pattern, replacement in _MASK_RULES:
        out = pattern.sub(replacement, out)
    return out


def main() -> int:
    problems: list[str] = []
    audits = {A5: audit_a5, A6: audit_a6, A2: audit_a2}
    for rel, auditor in audits.items():
        old_text = git("show", f"{OLD}:{rel}")
        new_text = git("show", f"{NEW}:{rel}")
        print(f"== {rel}")
        print(f"  blob old={blob_sha(OLD, rel)[:12]} "
              f"new={blob_sha(NEW, rel)[:12]} (changed="
              f"{blob_sha(OLD, rel) != blob_sha(NEW, rel)})")
        print(f"  sha256 old={sha256_text(old_text)[:16]} "
              f"new={sha256_text(new_text)[:16]}")
        old_p = auditor(old_text, f"{rel}@{OLD}")
        new_p = auditor(new_text, f"{rel}@{NEW}")
        print(f"  invariants old: {'OK' if not old_p else old_p}")
        print(f"  invariants new: {'OK' if not new_p else new_p}")
        same_structure = masked_structure(old_text) == \
            masked_structure(new_text)
        print(f"  run-identity-masked structure identical: {same_structure}")
        if not same_structure:
            problems.append(f"{rel}: masked structure differs between "
                            "versions — protocol/criterion drift suspected")
        problems.extend(old_p + new_p)
    msg = git("log", "-1", "--format=%s", NEW)
    disclosed = "regenerate" in msg.lower()
    print(f"== 2a60864 discloses regeneration in subject: {disclosed} "
          f"(subject: {msg})")
    if not disclosed:
        problems.append("commit subject does not disclose regeneration")
    if problems:
        print("AUDIT: VIOLATIONS FOUND")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("AUDIT: ALL PROTOCOL INVARIANTS HOLD ON BOTH VERSIONS; "
          "differences confined to run-identity facts; regeneration "
          "disclosed in the commit subject; old versions traceable "
          "in git history (git show a3bf463:<path>)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
