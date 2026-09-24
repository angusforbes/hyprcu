#!/usr/bin/env python3
"""Per-trial timing from a Pi session log, for the setup comparisons in
docs/COMPARE-1-10.md.

A trial starts at a bash command containing ": TRIAL-START <setup> <test>;"
and ends at the driver's next command that begins with ": TRIAL" (the next
trial or an explicit TRIAL-END) or is a reset/verification step. For each
trial it reports:

  total     wall clock from the trial's first command to the driver's next
            command after answering (includes the driver's thinking)
  computer  time the tools were actually running: for each command, from the
            call to its result (hyprcu, the helper models, screenshots)
  driver    total - computer: the driving model reading and deciding
  turns     tool calls in the trial; images = screenshots the driver read

Usage: tools/trial_times.py [SESSION.jsonl] [--setups S0,S3b] [--skip "S2 T2"]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from datetime import datetime

END_MARKERS = ("reset.sh", "kev_vision_serve", "python3 - <<'PY'", "v_s", "trial_times.py")


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load(path: str) -> list[tuple]:
    ev = []
    with open(path) as fh:
        lines = fh.readlines()
    for line in lines:
        r = json.loads(line)
        m = r.get("message") or {}
        if m.get("role") == "assistant":
            for c in m.get("content", []):
                if c.get("type") == "toolCall":
                    a = c.get("arguments", {})
                    ev.append((_t(r["timestamp"]), "call", c["name"].lower(),
                               a.get("command") or a.get("path") or ""))
        elif m.get("role") == "toolResult":
            ev.append((_t(r["timestamp"]), "result", "", ""))
    return ev


def trials(ev: list[tuple]) -> dict[str, dict]:
    calls = [i for i, e in enumerate(ev) if e[1] == "call"]
    out: dict[str, dict] = {}
    for k, i in enumerate(calls):
        name, cmd = ev[i][2], ev[i][3]
        if name != "bash" or not cmd.startswith(": TRIAL"):
            continue
        for mm in re.finditer(r": TRIAL-START (\S+) (T\d+);", cmd):
            key = f"{mm.group(1)} {mm.group(2)}"
            j = k + 1
            while j < len(calls):
                c2 = ev[calls[j]]
                if c2[2] == "bash" and (c2[3].startswith(": TRIAL")
                                        or any(m in c2[3] for m in END_MARKERS)):
                    break
                j += 1
            if j >= len(calls):
                continue
            computer = 0.0
            for c in calls[k:j]:
                res = next((ev[x][0] for x in range(c + 1, len(ev)) if ev[x][1] == "result"), None)
                if res is not None:
                    computer += (res - ev[c][0]).total_seconds()
            seg = [ev[c] for c in calls[k:j]]
            out[key] = {
                "total": (ev[calls[j]][0] - ev[i][0]).total_seconds(),
                "computer": computer,
                "turns": len(seg),
                "images": sum(1 for e in seg if e[2] == "read"
                              and re.search(r"\.(jpe?g|png)$", e[3])),
            }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?")
    ap.add_argument("--setups", default="")
    ap.add_argument("--skip", action="append", default=[])
    a = ap.parse_args()
    path = a.session or max(glob.glob(os.path.expanduser(
        "~/.pi/agent/sessions/--home-agf-Work--/*.jsonl")), key=os.path.getmtime)
    res = trials(load(path))
    setups = a.setups.split(",") if a.setups else sorted({k.split()[0] for k in res})
    tests = sorted({k.split()[1] for k in res}, key=lambda t: int(t[1:]))
    print("total s / computer s / turns / images the driver read")
    print("      " + "".join(f"{s:>22}" for s in setups))
    for t in tests:
        cells = []
        for s in setups:
            r = res.get(f"{s} {t}")
            skip = f"{s} {t}" in a.skip
            cells.append("-" if r is None else
                         f"{'(' if skip else ''}{r['total']:4.0f} / {r['computer']:4.1f} / "
                         f"{r['turns']} / {r['images']}{')' if skip else ''}")
        print(f"{t:>5} " + "".join(f"{c:>22}" for c in cells))
    for s in setups:
        rs = [v for k, v in res.items() if k.split()[0] == s and k not in a.skip]
        if not rs:
            continue
        tot = sum(r["total"] for r in rs)
        com = sum(r["computer"] for r in rs)
        print(f"{s}: total {tot:.0f} s = computer {com:.0f} s ({com / tot:.0%}) + driver "
              f"{tot - com:.0f} s; {sum(r['turns'] for r in rs)} turns, "
              f"{sum(r['images'] for r in rs)} images, {len(rs)} tests")


if __name__ == "__main__":
    main()
