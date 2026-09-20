#!/usr/bin/env python3
"""
Benchmark a kev (or Jev-compatible) server on window selection.

  kev_bench.py                 # run against http://127.0.0.1:8009
  kev_bench.py --url URL       # any /v1/systemone server (Jev, kev, openjev)
  kev_bench.py --none          # add an explicit "none of these" option

Uses the live window list from hyprctl, plus a fixed query set with
ground-truth answers so different models/sizes can be compared honestly.
"""
import json, subprocess, sys, time, urllib.request

URL = "http://127.0.0.1:8009/v1/systemone"
if "--url" in sys.argv: URL = sys.argv[sys.argv.index("--url") + 1]
WITH_NONE = "--none" in sys.argv

APP = {"io.github.lgse.Strata": "Strata file browser, file manager",
       "foot": "foot terminal, shell, command line",
       "chromium": "Chromium web browser", "brave-origin": "Brave web browser",
       "slack": "Slack chat, messaging", "md.obsidian.Obsidian": "Obsidian notes, markdown",
       "org.omarchy.agent": "AI agent pane, Claude Code, assistant chat"}

def windows():
    ws = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout)
    return [c for c in ws if c["mapped"] and c["workspace"]["name"] != "special:reprieve"]

def describe(c):
    t = c["title"]
    for s in (" - Chromium", " - Brave Origin", " - Google Search", " - Slack"): t = t.replace(s, "")
    return f"{t.strip(' ✳◑●○').strip()[:60]} — {APP.get(c['class'], c['class'])}"

def ask(query, ws):
    crit = {c["address"]: describe(c) for c in ws}
    instr = "Which open window best matches what the user described?"
    if WITH_NONE:
        crit["NONE"] = "None of the open windows match this description"
        instr += " If nothing fits, choose NONE."
    body = {"model": "kev", "state": f'The user wants to interact with: "{query}"',
            "questions": {"w": {"type": "choice", "instructions": instr, "criteria": crit}}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"content-type": "application/json"})
    t = time.time(); r = json.load(urllib.request.urlopen(req)); ms = int((time.time() - t) * 1000)
    a = r["answers"]["w"]
    return a["choice"], a["probabilities"][a["choice"]], ms

# (query, predicate on the window dict that means "correct"), or None = nothing open should match
def is_agent(c): return c["class"] == "org.omarchy.agent"
def is_term(c): return c["class"] == "foot"
def title_has(s): return lambda c: s.lower() in c["title"].lower()
CASES = [
    ("Claude Code",                          title_has("Claude Code")),
    ("the tic tac toe game",                 title_has("tictactoe")),
    ("the browser tab about screen timeout", title_has("screen")),
    ("the AI agent pane",                    is_agent),
    ("a terminal",                           is_term),
    ("the Heeler discussion",                title_has("Heeler")),
    ("slack",                                None),
    ("the file browser",                     None),
    ("obsidian",                             None),
]

def main():
    ws = windows()
    print(f"{len(ws)} windows, server={URL}, none_option={WITH_NONE}\n")
    right = 0; lat = []
    for q, pred in CASES:
        addr, p, ms = ask(q, ws); lat.append(ms)
        if addr == "NONE":
            ok = pred is None; got = "NONE"
        else:
            c = next(w for w in ws if w["address"] == addr)
            got = c["title"][:34]
            ok = (pred is not None and pred(c)) or (pred is None and p < 0.5)
        right += ok
        print(f"{'✓' if ok else '✗'} {q:38s} → {got:36s} {p:.2f} {ms:4d}ms")
    print(f"\n{right}/{len(CASES)} correct   median {sorted(lat)[len(lat)//2]}ms   warm-min {min(lat)}ms")

if __name__ == "__main__":
    main()
