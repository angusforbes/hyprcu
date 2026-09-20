#!/usr/bin/env python3
"""
Pick a window from a natural-language description using OpenDecision.

  window_pick.py "the file browser"
  window_pick.py "slack"
  window_pick.py "the terminal I was running tests in"
  window_pick.py --serve        # keep model warm, read queries from stdin

Prints: <address> <class> <title>   (or NONE if confidence too low)

Warm GPU call ≈ 80ms. Cold start ≈ 5s (60s the very first time for triton JIT).
"""
import json, subprocess, sys, time

sys.path.insert(0, "/home/agf/Work/OpenDecision/src")

MIN_PROB = 0.35   # below this, say NONE and let Claude decide

def windows():
    out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout
    ws = [c for c in json.loads(out) if c.get("mapped") and c["workspace"]["name"] != "special:reprieve"]
    return ws

APP_HINTS = {
    "io.github.lgse.Strata": "Strata file browser, file manager",
    "foot": "foot terminal, shell, command line",
    "chromium": "Chromium web browser",
    "brave-origin": "Brave web browser",
    "slack": "Slack chat, messaging, channels",
    "md.obsidian.Obsidian": "Obsidian notes, markdown, vault",
    "org.omarchy.agent": "AI agent pane, Claude Code, assistant chat",
}

def describe(c):
    """Title first (most distinguishing), then app hint. Strip boilerplate suffixes."""
    title = c["title"]
    for suffix in (" - Chromium", " - Brave Origin", " - Google Search", " - Slack"):
        title = title.replace(suffix, "")
    title = title.strip(" ✳◑●○").strip()[:60]
    hint = APP_HINTS.get(c["class"], c["class"])
    return f"{title} — {hint}"

_engine = None
def engine():
    global _engine
    if _engine is None:
        from opendecision.engine import OpenDecisionEngine
        _engine = OpenDecisionEngine()
    return _engine

def pick(query, ws=None):
    ws = ws or windows()
    if not ws:
        return None, 0.0, {}
    criteria = {c["address"]: describe(c) for c in ws}
    if len(criteria) == 1:
        addr = next(iter(criteria))
        return addr, 1.0, {addr: 1.0}
    res = engine().choice(
        state=f"The user wants to interact with: \"{query}\"",
        instructions="Which open window best matches what the user described?",
        criteria=criteria,
    )
    addr = res["choice"]
    return addr, res["probabilities"][addr], res["probabilities"]

def fmt(addr, ws):
    c = next((w for w in ws if w["address"] == addr), None)
    return f"{addr} {c['class']} {c['title'][:60]}" if c else "NONE"

def main():
    if "--serve" in sys.argv:
        engine()  # warm
        print("READY", flush=True)
        for line in sys.stdin:
            q = line.strip()
            if not q: continue
            ws = windows()
            t = time.time()
            addr, p, _ = pick(q, ws)
            ms = int((time.time() - t) * 1000)
            print(f"{fmt(addr, ws) if p >= MIN_PROB else 'NONE'}\t{p:.2f}\t{ms}ms", flush=True)
        return
    query = " ".join(a for a in sys.argv[1:] if not a.startswith("--"))
    ws = windows()
    t = time.time()
    addr, p, probs = pick(query, ws)
    ms = int((time.time() - t) * 1000)
    if "--verbose" in sys.argv:
        for a, pr in sorted(probs.items(), key=lambda x: -x[1]):
            print(f"  {pr:.2f}  {fmt(a, ws)}", file=sys.stderr)
    print(f"{fmt(addr, ws) if p >= MIN_PROB else 'NONE'}\t{p:.2f}\t{ms}ms")

if __name__ == "__main__":
    main()
