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

# CLI — same functions, ~20 ms installed binary (few hundred ms via `uv run`)
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

---

## Session 2 addendum — 2026-09-20, Grip2 (anthropic/claude-opus-5)

Grip's handoff above is still accurate. What changed since:

**CI was red and silently so.** `uv run ruff check .` (exactly what `.github/workflows/ci.yml`
runs) reported **102 violations**, so no PR/release could have passed. Fixed by reformatting,
not by adding ignores or noqa: semicolon-joined statements split, one-line `if` bodies
expanded, long lines wrapped, imports sorted. `tools/` was delegated to a subagent under a
formatting-only brief and the diff checked for logic changes (none). Now clean.

**New `src/hyprcu/cleanup.py` — re-armed the drag button-release.** Upstream released a held
mouse button on SIGTERM; in this fork that was *double-dead*: `safety.on_shutdown` is a no-op
stub, AND its only caller in `verbs.py` gated on `cli._take_beacon()` which returns `True`, so
`arm()` never executed. A verb killed mid-drag could strand a held button on the virtual
pointer. The removed *beacon* was trust/approval machinery; the button-release is OS hygiene,
so it got its own module rather than reviving `safety`. `safety.py` stays a no-op stub and its
`touch()` calls are untouched. `journal.start`/`journal.stop` were dropped from the server
lifecycle — the training log appends per row (open/write/close), so there is nothing to flush,
and both were no-op stubs anyway.

Verified with unit tests (`tests/test_cleanup.py`) *and* a real `pty.fork` harness: a process
killed mid-hold exits 143 and `release_held` fires. `tests/test_verbs.py` updated; the obsolete
`test_take_beacon_is_used_when_no_server_holds_it` deleted (it tested a removed concept).

**Docs corrected against measurement, not memory:**
- README said 359 passed / 54 xfailed → actually **362 / 53**.
- README listed `journal.py` under "replaced with no-op stubs" → it is a **live training log**,
  wired to all 15 tools via `@journal.journaled`. Only `trust.py`/`safety.py`/`skill.py` are stubs.
- Latency claimed 150ms (README/HANDOFF) and 300ms (`cli.py` docstring) → measured **~20 ms**
  cold for the installed binary; the 150–300 ms figure is `uv run` overhead. All three aligned.
- `ARCHITECTURE.md` still documented upstream's trust layers, journal/dry-run/replay and a
  `scripts/` dir that does not exist → rewritten to describe hyprcu as it is, including `pick.py`
  (kev targeting), window-relative coordinates, and the real testing tiers.
- `docs/TESTS.md` given a status banner: it is the historical record of the **retired**
  `desktop.ts`, and **T22–T25 have NOT been rerun under hyprcu**.

**Gates now:** `ruff check .` clean · `pytest -q` 362 passed / 53 xfailed · `pytest -m e2e`
12 passed, 1 skipped. Pushed as `54702ea` and `49fcb39`.

**kev is no longer hand-launched.** It runs as a systemd *user* unit,
`~/.config/systemd/user/kev.service` (enabled, autostarts at login, CUDA + NF4).
`systemctl --user status|restart kev`. Its first start hung: the process sat in `SYN-SENT` to an
IPv6 :443 — a Hugging Face hub metadata call dying on the corporate VPN — so the unit sets
`HF_HUB_OFFLINE=1`. All weights (kev-4b adapter + Qwen3-4B base, 7.6G) are cached, so this costs
nothing and removes the network from the startup path. Binds in ~25s. Verified end to end:
`pick.resolve("the AI agent pane")` → `[kev: 86% in 256ms]`. `tools/kev-serve.sh` remains as the
manual fallback and mirrors the unit's env.

**Still not done (unchanged from Grip's list):** T22–T25 under hyprcu. I attempted T22 and the
board reader mis-read an empty grid as "O wins in 0 moves" — the `ttt.sh` grid-math fragility
Grip flagged is real and still unfixed. The Jev A/B and the kev NF4 upstream PR are also still open.

**One warning for whoever runs the live tests:** if a typed command leaves the shell in quote
continuation, every later Enter only adds a newline and nothing executes — it looks exactly like
"hyprcu isn't delivering Enter". Send `ctrl+c` before typing to reset. Also note
`hyprcu sequence`'s keyboard `key` op wants a **string**, not a list; passing `{"keys":["Return"]}`
raises `'list' object has no attribute 'split'` (the standalone `hyprcu keyboard key Return`
takes it fine). Worth fixing or documenting.
