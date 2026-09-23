# hyprcu — HANDOFF

*Rewritten 2026-09-23 by help[b] (anthropic/claude-opus-5-5). Replaces the
session-1/2 handoffs (Grip, Grip2); their history is in git
(`git show a305ecb:HANDOFF.md`).*

## What this is

**Hyprland computer use for AI agents.** An MCP server + CLI (one binary) that
lets an agent see and drive the desktop with no approval dialogs. Fork of
[hypruse](https://github.com/IlyasKhallouki/hypruse) (MIT). What hyprcu adds:

1. **Description targeting.** Every `window=` accepts an address, a
   class/title substring, or a description ("the file browser"). `click_ui`
   accepts a control's exact name *or* a description ("submit the form").
   Descriptions go to a **chooser**: TypeSafe **Jev** (default, cloud) or local
   **kev** (`HYPRCU_CHOOSER=kev`). Code: `src/hyprcu/pick.py`.
2. **Fast accessibility.** In-process D-Bus + AT-SPI Collection, so `ui` and
   `click_ui` cost ~0.2–0.3 s instead of 3–5 s.
3. **Window-relative coordinates**, a **training log**
   (`~/.local/share/hyprcu/actions.jsonl`), and the nested test harness below.

Repo: https://github.com/angusforbes/hyprcu

## Privacy / key requirement (must stay explicit)

Jev is the default. A description call **sends window titles/classes or
control names/values, plus the description, to TypeSafe**, and needs
`TYPESAFE_API_KEY` in the environment (never written to disk). Addresses and
exact names/substrings stay local. Without a key, descriptions fail with a
message saying so; `HYPRCU_CHOOSER=kev` keeps everything on the machine. This
is stated in the README section "Requires a TypeSafe API key" — keep it true.

## Current state (verified 2026-09-23)

- `ruff check .` clean · `pytest -q` **391 passed**, 53 xfailed · `pytest -m e2e`
  7 passed (against the nested session).
- **6 local commits NOT pushed** (`8335af5`..`d224f47`). Push when Angus says.
- Pi's `~/.pi/agent/mcp.json` sets `HYPRCU_CHOOSER=jev` for the hyprcu server
  (backup: `mcp.json.bak-20260923-030548`). Pi panes need `/reload` to pick up
  the config and new code.
- `kev.service` (systemd user unit) still runs; only needed for `HYPRCU_CHOOSER=kev`
  or the benchmark.

### What changed this session, with measurements

| change | before → after |
|---|---|
| a11y transport: jeepney connection instead of one `busctl` per call; Collection.GetMatches + pipelined reads | Chromium `ui` 5.2 s → 0.22 s; `click_ui` 3.4 s → 0.33 s; identical elements/order |
| Virtual keyboard on real US keycodes (wtype-style 1,2,3… put `/` on Escape and `-` on Backspace; Chromium reads punctuation by keycode) | `/abc` → `abc` and `abcdefghijklm-z` → `abcdefghijklz` fixed; unicode and combos verified in Chromium and foot |
| Our own keyboard on the default seat (wtype only as fallback): needed a bound `wl_seat`, ids in allocation order, and the modifiers request | `ctrl+a` no longer arrives as `a` |
| Chromium coordinate mapping: UI is in a scaled unit (frame 1147×705 for a 1558×958 window, ×1.358), web content in physical pixels (÷ monitor scale) | Back/Reload/New Tab/tab close land exactly; web elements would have been 1.6× off on the 1.6-scale host |
| Jev chooser with explicit NONE; `click_ui` by description | see benchmark below |

**Browser A/B (3 tasks, nested session, one run):** accessibility-first 4 calls,
0 screenshots, ~1.7 min; screenshot-first ~19 calls, 6 screenshots, ~12 min.
Both include model thinking time; most of the gap is reading images.

**Chooser benchmark** (`tools/choice_bench.py`, 29 synthetic queries incl. 5
with no right answer; nothing from the live desktop is sent):

| | kev-4b (local GPU, NF4) | Jev |
|---|---|---|
| explicit NONE option | 20/29, 1.8–2.8 s | **28/29, ~0.6 s** |
| gate 0.5, no NONE | 25/29, 1.7–2.7 s | 25/29, ~0.3 s (never abstains) |

Live Jev in the nested session (~0.3 s each): "the terminal"/"the web browser"
focus correctly; "my email client" refused; "get in touch with them" → Contact
form; "send it" → Send message; "go back to the previous page" → Back; "log out
of my account" → none (95%).

## Invisible testing: the nested session

A second Hyprland runs inside a window on host **workspace 9**; its real
output is disabled and a **headless** output hosts its workspaces, so it renders
and screenshots (~0.24 s) without appearing on Angus's screen, and its
keyboard/pointer never touch his seat (verified: host focus and cursor
unchanged). Files in `/tmp/hyprcu-nested/` (lost on reboot):

- `hyprland.lua` — minimal config; `env.sh` — `HYPRLAND_INSTANCE_SIGNATURE`,
  `WAYLAND_DISPLAY=wayland-2`, `HYPRCU_CHOOSER=jev`
- `site/` — test pages (home with links + counter, contact form, about page with
  a secret word) served by `python3 -m http.server 8765 --bind 127.0.0.1`
- `chromium-profile/` — throwaway profile (`--force-renderer-accessibility`)

Recreate after a reboot (host commands):

    hyprctl dispatch 'hl.dsp.exec_cmd("[workspace 9 silent] Hyprland -c /tmp/hyprcu-nested/hyprland.lua")'
    # then, with the NEW instance signature and wayland socket in env.sh:
    hyprctl output create headless TEST
    hyprctl eval 'hl.monitor({ output = "WAYLAND-1", disabled = true })'

Use it with `. /tmp/hyprcu-nested/env.sh; ~/Work/hyprcu/.venv/bin/hyprcu …`.
The Hyprland dispatch syntax is Lua (`hl.dsp.*`), not the old keyword form.
Screenshots of the nested window's own output hang (grim on the nested
WAYLAND-1) — that is why the headless output exists.

## Known issues / rough edges

- `sequence`'s keyboard `key` op wants a **string** (`"keys": "Return"`); a list
  raises `'list' object has no attribute 'split'`.
- `wait_for title_change` started *after* an action can miss a fast page load;
  put the action and the wait in one `sequence`.
- Chromium's first click on a tab can show the hover card instead of switching;
  prefer `ctrl+N` / `ctrl+Tab`.
- The Chromium document scale heuristic picks the largest of {1, 1/monitor scale,
  UI scale} that fits the window; tested at monitor scale 1 (nested) and 1.6
  (host geometry only, not clicked). Split view / zoomed pages untested.
- a11y is still app-dependent: Strata exposes ~1 element, Slack 0 (Electron needs
  `--force-renderer-accessibility`). Chromium here is launched with that flag.
- kev NF4 patch in `~/Work/kev` is uncommitted (see git history of this file).
- Agent-side lesson: never read a file in the same parallel batch as the command
  that writes it — the read runs first and fails with ENOENT.

## Testing round 3 (2026-09-23, paused mid-way)

- **T22 Google tic-tac-toe: PASS** — won as X (centre, corner, fork), board typed
  into foot via `cat` + ctrl+d. ~9 calls, 5 screenshots (4 small board crops);
  the board is not in a11y but the score ("X 1") is.
- **Stuck Super in the nested session** (not a hyprcu bug): the nested compositor
  gets the host keyboard, so Super pressed while its window had host focus stayed
  "held"; all combos failed in Chromium (wtype too) and Return in foot printed
  `;9;13~`. Fixed by restarting: `tools/nested-session.sh` (new, one command).
- **OPEN BUG, fix next:** `ui` silently caps at 60 elements (`a11y.find_elements`
  max_results); the Collection fast path always returns truncated=False and
  `_ui_read` only mentions truncation when the list is empty. On Google, page
  content past the browser chrome was cut. Fix: report the dropped count
  and say so in the `ui` output (and consider a higher cap now reads are cheap).
- **Friction to fix:** `sequence` steps use `op` (error says "unknown step op
  None" when given `tool`); `hypr` names its window arg `target` while every
  other tool uses `window`; Jev latency now 0.6–0.9 s (was ~0.3 s).
- Not yet run: T11/T15/T16/T18/T21, Omarchy desktop tasks. T23–T25 need Angus's
  real Slack/vibezAI accounts.

## Next steps

1. **More testing in the nested session** (Angus's next ask): rerun T22–T25
   (`docs/TESTS.md` — tic-tac-toe, vibezAI, Slack) and Omarchy desktop tasks
   (workspaces, binds, launcher/bar via `layers`), counting calls/screenshots.
2. Push the 6 commits once Angus approves.
3. Use Jev to cut screenshot fallbacks further: for canvas/inaccessible UIs,
   try targeted checks before a full screenshot + vision round trip.
4. Test the Chromium scale mapping by *clicking* on the 1.6-scale host monitor.
5. Label `actions.jsonl` rows (`correct`) before any training use.

## Ideas (not built)

- **Screenshot cost plan** (capture is cheap, ~80 ms/90 KB full-res nested; the
  model reading images is the cost): (1) auto-crop to the known target/affected
  region, (2) return only the changed region vs the last shot ("nothing changed"
  = no image), (3) answer simple questions locally (tesseract OCR, pixel/template
  checks, small VLM), (4) default size budget (host is 1.6x scale), (5) use
  `--stable` instead of sleeps. Start with 1+2; measure against T22 baseline
  (9 calls, 5 screenshots).
- **"Show the agent" (grim + slurp):** a keybind where Angus drags a region with
  slurp, grim captures it, and hyprcu hands it to the agent with a question.
  Human-to-agent only; agents' own shots keep computed regions.

## Where things are

| what | path |
|---|---|
| source | `~/Work/hyprcu/src/hyprcu/` — `pick.py` (choosers), `a11y.py`, `wire.py` (keyboard), `server.py` |
| lessons + app profiles | `docs/LESSONS.md` |
| test list (historical results) | `docs/TESTS.md` |
| benchmarks | `tools/choice_bench.py` (+ `choice_bench_fixtures.json`), `tools/kev_bench.py` |
| nested session | `/tmp/hyprcu-nested/` |
| kev model / unit | `~/Work/kev`, `~/.config/systemd/user/kev.service` |
| upstream reference | `~/Work/hypruse` |
