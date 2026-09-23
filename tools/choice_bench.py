#!/usr/bin/env python3
"""
A/B kev (local) vs Jev (TypeSafe cloud) on the two choices hyprcu cares about,
using SYNTHETIC inputs only (nothing from the live desktop leaves the machine):

  window   -- which of these open windows did the user mean?
  control  -- which control on this page does the request refer to?
              (candidates are real `hyprcu ui` output captured from a local
              test site, stored in choice_bench_fixtures.json)

Every question offers an explicit NONE option, and some queries have no right
answer, so a model is scored on abstaining as well as on picking.

  choice_bench.py                  # both backends
  choice_bench.py --only kev|jev
  choice_bench.py --runs 2         # repeat each query (latency spread)
  choice_bench.py --gate 0.5       # no NONE option; abstain when p < gate
                                   # (how hyprcu's pick.py uses kev today)

Jev needs TYPESAFE_API_KEY in the environment (never written to disk here).
"""

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKENDS = {
    "kev": ("http://127.0.0.1:8009/v1/systemone", "kev", None),
    "jev": ("https://api.typesafe.ai/v1/systemone", "jev-latest", "TYPESAFE_API_KEY"),
}
NONE = "NONE"
GATE = float(sys.argv[sys.argv.index("--gate") + 1]) if "--gate" in sys.argv else None

WINDOWS = {
    "w1": "~/Work/project — foot terminal, shell, command line",
    "w2": "Contact Form — Chromium web browser",
    "w3": "GitHub - acme/widgets: Pull request #42 — Chromium web browser",
    "w4": "Downloads — Strata file browser, file manager",
    "w5": "general (Channel) - Acme — Slack chat, messaging",
    "w6": "Meeting notes - Vault — Obsidian notes, markdown",
    "w7": "holiday.mp4 — mpv media player",
    "w8": "Calculator — GNOME Calculator",
    "w9": "budget.ods — LibreOffice Calc spreadsheet",
    "w10": "Pi agent — AI agent pane, assistant chat",
}
WINDOW_QUERIES = [
    ("the terminal", {"w1"}),
    ("the browser with the pull request", {"w3"}),
    ("the contact form page", {"w2"}),
    ("the file browser", {"w4"}),
    ("the chat app", {"w5"}),
    ("my notes", {"w6"}),
    ("the video I was watching", {"w7"}),
    ("the calculator", {"w8"}),
    ("the spreadsheet with the budget", {"w9"}),
    ("the AI assistant", {"w10"}),
    ("my email client", {NONE}),
    ("the PDF I was reading", {NONE}),
]

# (page, request, acceptable control names; NONE = nothing on the page does it)
CONTROL_QUERIES = [
    ("home", "increase the counter", {"Increment"}),
    ("home", "read about the company", {"About us"}),
    ("home", "get in touch with them", {"Contact form"}),
    ("home", "go back to the previous page", {"Back"}),
    ("home", "refresh the page", {"Reload"}),
    ("home", "open a new tab", {"New Tab"}),
    ("home", "bookmark this page", {"Bookmark this tab"}),
    ("home", "log out of my account", {NONE}),
    ("home", "submit the form", {NONE}),
    ("form", "submit the form", {"Send message"}),
    ("form", "enter my email", {"Email address"}),
    ("form", "fill in my name", {"Your name"}),
    ("form", "sign me up for updates", {"Subscribe to newsletter"}),
    ("form", "choose what the message is about", {"Topic"}),
    ("form", "return to the start page", {"Back home"}),
    ("form", "type a web address", {"Address and search bar"}),
    ("form", "play the video", {NONE}),
]


def control_criteria(page: str, fixtures: dict) -> tuple[dict, dict]:
    crit, names = {}, {}
    for i, c in enumerate(fixtures["pages"][page]):
        where = "browser toolbar or tab strip" if c.get("y", 999) < 140 else "web page content"
        desc = f'{c["role"]} "{c["name"]}" ({where})'
        if "value" in c:
            desc += f" value={c['value']!r}"
        crit[f"c{i}"] = desc
        names[f"c{i}"] = c["name"]
    return crit, names


def ask(backend: str, state: str, instructions: str, criteria: dict) -> tuple[str, float, int]:
    url, model, key_env = BACKENDS[backend]
    headers = {"content-type": "application/json"}
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise SystemExit(f"{key_env} not set")
        headers["authorization"] = f"Bearer {key}"
    body = {
        "model": model,
        "state": state,
        "questions": {
            "q": {"type": "choice", "instructions": instructions, "criteria": criteria}
        },
    }
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    for attempt in range(4):
        t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            ms = int((time.perf_counter() - t) * 1000)
            a = data["answers"]["q"]
            return a["choice"], float(a["probabilities"][a["choice"]]), ms
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 3:
                time.sleep(0.5 * 2**attempt)
                continue
            raise


def run(backend: str, fixtures: dict, runs: int) -> dict:
    rows = []
    instr_w = (
        "Which open window best matches what the user described? "
        "If none of them fits, choose NONE."
    )
    crit_w = dict(WINDOWS)
    if GATE is None:
        crit_w[NONE] = "None of the open windows match this description"
    else:
        instr_w = "Which open window best matches what the user described?"
    for query, good in WINDOW_QUERIES:
        for _ in range(runs):
            ch, p, ms = ask(backend, f'The user wants to interact with: "{query}"', instr_w, crit_w)
            if GATE is not None and p < GATE:
                ch = NONE
            rows.append(("window", query, ch, p, ms, ch in good, NONE in good))
    instr_c = (
        "Which control should be activated to do what the user asked? "
        "If no control on this page does it, choose NONE."
    )
    for page, query, good in CONTROL_QUERIES:
        crit, names = control_criteria(page, fixtures)
        if GATE is None:
            crit[NONE] = "No control on this page does what the user asked"
        else:
            instr_c = "Which control should be activated to do what the user asked?"
        for _ in range(runs):
            ch, p, ms = ask(backend, f'The user asked: "{query}"', instr_c, crit)
            if GATE is not None and p < GATE:
                ch = NONE
            picked = NONE if ch == NONE else names.get(ch, ch)
            rows.append(("control", query, picked, p, ms, picked in good, NONE in good))
    return {"rows": rows}


def report(backend: str, res: dict) -> None:
    rows = res["rows"]
    print(f"\n== {backend} ==")
    for suite in ("window", "control"):
        sub = [r for r in rows if r[0] == suite]
        ok = sum(r[5] for r in sub)
        absent = [r for r in sub if r[6]]
        lat = sorted(r[4] for r in sub)
        p90 = lat[int(len(lat) * 0.9) - 1]
        print(
            f"{suite:8} correct {ok}/{len(sub)}  "
            f"abstained-correctly {sum(r[5] for r in absent)}/{len(absent)}  "
            f"latency median {statistics.median(lat)} ms  p90 {p90} ms"
        )
        for r in sub:
            if not r[5]:
                print(f"   MISS {r[1]!r} -> {r[2]!r} ({r[3]:.0%})")


def main() -> None:
    fixtures = json.loads((Path(__file__).parent / "choice_bench_fixtures.json").read_text())
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 1
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    for backend in [only] if only else list(BACKENDS):
        report(backend, run(backend, fixtures, runs))


if __name__ == "__main__":
    main()
