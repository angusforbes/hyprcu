# hyprcu — HANDOFF

*2026-09-20 12:26 CDT · written by Grip (claude-opus-4-6) at end of a ~28h session*

## What this is

**Hyprland computer use for AI agents.** An MCP server + CLI that lets an agent
see and drive the desktop with **no approval dialogs and no built-in refusals**.
Fork of [hypruse](https://github.com/IlyasKhallouki/hypruse) (MIT) with its
trust/journal/safety layers removed and three things added:

1. **Natural-language window targeting** — every `window=` arg accepts an
   address, a class/title substring, or a description ("the file browser").
   Descriptions go to **kev-4b**, a local Jev-compatible decision model, ~300ms.
2. **Window-relative coordinates** — `pointer` takes `window` + `x_pct/y_pct`
   (0–1). Survives moves/resizes.
3. **A training log** of every acting call, with kev query+probability when used.

Repo: https://github.com/angusforbes/hyprcu (public, 17 commits, 362 tests).

## How to run

```
# MCP (already in ~/.pi/agent/mcp.json as "hyprcu"; /reload to pick up changes)
uv run --directory ~/Work/hyprcu python -m hyprcu

# CLI — same functions, ~150ms per call
uv run --directory ~/Work/hyprcu hyprcu desktop
uv run --directory ~/Work/hyprcu hyprcu hypr focus_window "the file browser"
uv run --directory ~/Work/hyprcu hyprcu pointer click --in Strata --at 0.053 0.23
uv run --directory ~/Work/hyprcu hyprcu --help

# kev (needed for description targeting; substrings/addresses work without it)
# DO NOT start from a one-shot bash call (Lesson 25). Use a persistent pane or:
setsid -f ~/Work/hyprcu/tools/kev-serve.sh > /tmp/kev.log 2>&1 < /dev/null
# ~60s to load, 3.6 GB VRAM. Check: ss -ltn | grep 8009

# tests
cd ~/Work/hyprcu && uv run pytest tests/ -q --ignore=tests/test_e2e.py
```

## Current state (verified)

- **T1–T21 pass** under hyprcu (`docs/TESTS.md`). T1–T10 in 4.7 s total.
  T16 (drag) is a definitive "Strata has sweep-select, not DnD" — the unified
  pointer works; retest on an app with drop targets.
- **T22–T24 not rerun under hyprcu** — the session locked mid-test (see below).
  They passed earlier under the retired `desktop.ts`. Rerun:
  `tools/ttt_fast.py --no-model` (needs the tictactoe tab fullscreen and the
  page scrolled to top), then the vibezAI and Slack flows in TESTS.md.
- kev-4b bench: 7/9 on `tools/kev_bench.py`, median 405 ms. (Was 173 ms this
  morning on a bf16 server that later OOM'd; NF4 costs ~2×.)
- All processes stopped at handoff: kev, subagent, inhibitor, test windows.
  `ydotoold.service` (system unit at /etc/systemd/system/) still runs; we no
  longer use it — `sudo systemctl disable --now ydotoold`.

## Decisions and why

- **Removed guards, kept observations.** Anything where the tool *decides not
  to act* is gone (trust layer, sequence abort-on-change, step/time caps,
  clamped timeouts). Anything that *reports state the agent can't see* stays
  and goes first: `SESSION_LOCKED`, `display: off`, kev-unreachable.
  `tests/test_no_guards.py` pins this. Lesson 28 is the cost of getting it wrong.
- **kev over Jev/OpenDecision/Needle.** OpenDecision (NLI) was near-random on
  short labels; Needle is tool-call-shaped not choice-shaped; Jev needs an API
  key (Angus may get one — `tools/kev_bench.py --url` is the A/B). kev-4b was
  9/9 first try. Lessons 17–19.
- **Kept `server.py` mergeable with upstream.** Only ~6 surgical edits; the
  rest is stubs (`trust.py`, `journal.py`, `safety.py`) with upstream's names.
- **CLI verbs restored** after I wrongly removed them — Codex/bash agents need
  them; one binary is both server (no args) and CLI.
- **`desktop.ts` (Pi extension) retired**; everything it did is in hyprcu.
  `pi-omarchy-computer-use` archived with a pointer.

## Known bugs / rough edges

- **kev NF4 patch is in `~/Work/kev` (jaredpalmer/kev), uncommitted.** Two
  edits in `kev/evaluate.py`: `KEV_QUANT=nf4` support, and `m.head.to(dev)` in
  the quantized branch (was left on CPU → 4.5 s/call). Worth a PR upstream.
- `sequence` steps are run sequentially in-process; a step that raises stops
  the run (by design — that's an error, not a guard).
- `hyprcu desktop` CLI one-liner omits some JSON keys; `--json` isn't a flag
  on that verb (use the MCP or `python -m hyprcu` for full JSON).
- a11y (`ui`/`click_ui`/`marks`) is nearly empty on this desktop: Strata
  exposes 1 element, Slack 0 (Electron needs `--force-renderer-accessibility`).
  Not a hyprcu bug; app-side.
- Two same-titled windows (two Chromiums on one search) are indistinguishable
  to kev — pass an address.

## Next steps, in order

1. **kev as a systemd user unit** so no agent ever launches it by hand again.
2. Rerun T22–T24; fix `tools/ttt.sh` grid math for non-fullscreen windows.
3. Try Jev when the key arrives: `tools/kev_bench.py --url https://…/v1/systemone`.
4. PR the NF4 patch to jaredpalmer/kev.
5. Route real tasks through hyprcu and see what the next app profiles need
   (`docs/LESSONS.md`, `grep "app profile"` — Strata, Chromium, Slack, vibezAI,
   Omarchy bar so far).
6. Consider `HYPRCU_READONLY=1` mode docs — it still exists as opt-in.

## Where things are

| what | path |
|---|---|
| server / CLI source | `~/Work/hyprcu/src/hyprcu/` |
| the additions | `pick.py` (kev), `journal.py` (log), `cli.py`; `pointer` in `server.py` |
| lessons (28) + 5 app profiles | `~/Work/hyprcu/docs/LESSONS.md` |
| 25 tests, 3 runs of results | `~/Work/hyprcu/docs/TESTS.md` |
| kev launcher / bench / ttt scripts | `~/Work/hyprcu/tools/` |
| training log | `~/.local/share/hyprcu/actions.jsonl` (unlabelled; add `correct` before training) |
| upstream reference | `~/Work/hypruse` (untouched clone) |
| kev model repo (patched) | `~/Work/kev` |
| dead weight, safe to delete | `~/Work/OpenDecision`, `~/Work/pi-omarchy-computer-use` (archived on GitHub) |

## The one thing to read first

`docs/LESSONS.md` §25 and §28. Both are about the agent (me) creating the
problem it then debugged: starting servers from a bash tool that kills them,
and stripping the lock check that would have said "you're typing into a
password field". If something "flaky" appears, check whether you caused it
before blaming the tool.
