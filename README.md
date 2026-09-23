# hyprcu

**Hyprland computer use.** Dialog-free desktop control for AI agents: an MCP
server and a CLI over the same primitives. A fork of
[hypruse](https://github.com/IlyasKhallouki/hypruse) (MIT, IlyasKhallouki) — see [Lineage](#lineage)
with the trust, journal, safety-beacon and CLI layers removed, keeping the
Wayland/Hyprland primitives intact. App knowledge and tooling live in `docs/` and `tools/`.

## Requires a TypeSafe API key (sends names to TypeSafe)

By default hyprcu resolves descriptions (`window="the file browser"`,
`click_ui "submit the form"`) with **TypeSafe's Jev** model, a cloud API.
Each such call **sends the candidate names to TypeSafe**: the titles and
classes of your open windows, or the names and values of the window's
accessible controls, plus your description. Addresses and exact names/
substrings resolve locally and send nothing.

- Get a key from [TypeSafe](https://typesafe.ai) and export `TYPESAFE_API_KEY`
  in the environment hyprcu runs in. It is read from the environment only and
  never written to disk.
- Without a key, descriptions fail with an explicit message; everything else
  works.
- To keep everything on the machine, set `HYPRCU_CHOOSER=kev` and run the local
  kev model instead (slower and less accurate; see below).

## What's kept from upstream

| module | what |
|---|---|
| `wire.py` | raw `zwlr_virtual_pointer_v1` client — motion+button+axis from one pointer, so drag works. hyprcu: the virtual keyboard puts every key on its real US keycode (wtype-style numbering made Chromium read '/' as Escape and '-' as Backspace) |
| `a11y.py` | AT-SPI tree. hyprcu: in-process D-Bus (jeepney) + Collection fast path instead of one `busctl` per call (Chromium `ui`: 5.2 s → 0.22 s); `busctl` remains the fallback |
| `events.py` | Hyprland socket2 listener → `wait_for`, event-driven `launch`/`close_window` |
| `hyprctl.py` | IPC layer; handles both hyprlang and Lua-dispatch Hyprland |
| `input.py`, `screenshot.py`, `clipboard.py`, `session.py` | as upstream, except typing/combos go through our virtual keyboard (wtype only as a fallback) |
| `server.py` | the MCP server; hyprcu adds window description resolution, `click_ui` by description, and per-toolkit accessibility coordinate mapping (Chromium UI vs web content) |

## What's replaced with no-op stubs

`trust.py`, `safety.py`, `skill.py` — same public names, every guard passes,
no log call does anything. `journal.py`
is NOT a stub: it is the training log (see below).

## What's removed

`waybar/`, `packaging/`, and upstream's `init` wizard, `journal`/`replay`
commands and skill installer.

## CLI (shell verbs) — kept

Every MCP tool is also a shell verb (the installed `hyprcu` binary starts
in ~20 ms cold; a few hundred ms under `uv run`) for agents that only
have bash (Codex, Claude Code in a terminal, scripts):

    hyprcu                                  # no args = MCP server on stdio
    hyprcu desktop                          # one line per monitor/workspace/window
    hyprcu screenshot --window 0x…          # prints path + {"geometry","scale",…}
    hyprcu hypr focus_window 0x…
    hyprcu pointer click 800 60
    hyprcu keyboard type "hello" --window 0x…
    hyprcu sequence '[{"op":"keyboard","action":"type","text":"x"},…]'
    hyprcu doctor                           # check binaries + session
    hyprcu stop                             # kill any running server/verb

Exit codes: 0 delivered · 1 error · 2 usage · 3 refused (read-only) · 4 no result.

## Tests

`uv run pytest tests/ --ignore=tests/test_e2e.py` → 362 passed, 53 xfailed.
The xfails are enumerated in `tests/removed_guard_tests.txt`; each asserts
that a guard refuses something. They are `strict`, so a guard silently
coming back would fail the suite.

## Run

    uv sync
    uv run python -m hyprcu        # MCP server on stdio

Tools: desktop, screenshot, zoom, ui, marks, binds, wait_for, pointer,
keyboard, click_ui, hypr, launch, use_bind, sequence.

## Measured on this machine (2026-09-20)

- `launch foot` → 167ms, returns address (event-driven, no sleep)
- `sequence` type+enter → 627ms, one round-trip
- `close_window` → 3ms, confirms destroy event
- `ui` on Strata: 1 element (sidebar toggle only — custom-drawn list)
- `ui` on Slack: 0 elements (Electron, needs `--force-renderer-accessibility`)

The a11y tools are only as good as the apps' trees. On this desktop, today,
they're mostly empty. `sequence`, `launch`, `wait_for` and the unified
pointer are the real gains.

## What hyprcu adds (the parts that are ours)

**`pick.py` — natural-language window targeting.** Every `window` argument
(hypr, pointer, keyboard, screenshot, ui, click_ui…) accepts an address, a
class/title substring, or a description. Resolution: exact address → unique
substring (free) → kev choice (~200ms, local). Ambiguous substrings are also
tie-broken by kev. Below `KEV_GATE` (0.5) it fails with "the app may not be
open — check desktop() or launch it", which has been right every time so far.
Results carry `[kev: 99% in 229ms]` so you can see when it was used.

    hyprcu hypr focus_window "the file browser"
    hyprcu keyboard type "hello" --window "the shell on workspace 2"

**Choosers: Jev (default) or kev.** By default these choices go to TypeSafe's
Jev (`TYPESAFE_API_KEY` from the environment) with an explicit "none of these"
option; this sends window titles and control names to TypeSafe (see
[Requires a TypeSafe API key](#requires-a-typesafe-api-key-sends-names-to-typesafe)).
`HYPRCU_CHOOSER=kev` uses the local model with a probability gate instead. `tools/choice_bench.py` (29 synthetic queries, nothing from the live
desktop): Jev 28/29 at ~0.6 s; kev-4b 20-25/29 at 1.7-2.8 s on a laptop GPU
(kev slows as the option list grows).

**`click_ui` by description.** When no control is *named* what you asked,
`click_ui` treats it as a description and the chooser picks among the
window's clickable controls (browser controls are labelled web page vs
toolbar), or refuses when none fits:

    hyprcu click_ui "submit the form" --window "the web browser"
    # clicked button 'Send message' ... [jev: 92% in 294ms]

**Window-relative clicks.** `pointer` takes `window` + `x_pct`/`y_pct`
(0.0–1.0); the window is focused first and the fraction is mapped to its
current geometry, so the click survives moves and resizes. CLI:
`hyprcu pointer click --in "Strata" --at 0.053 0.23`.

**`journal.py` — training log.** Acting tools append one JSONL row to
`~/.local/share/hyprcu/actions.jsonl` (`HYPRCU_LOG=0` disables): args,
the window list at the time, result, and — when kev chose — query and
probability. Rows are unlabelled; a `correct` field is meant to be added
later before anything is trained on them.

With `HYPRCU_CHOOSER=kev`, requires a Jev-compatible server at `KEV_URL` (default kev-4b on :8009).
The canonical launcher is the systemd user unit `kev.service`
(`systemctl --user start/stop/status kev`; runs on CUDA in NF4, offline-safe,
auto-starts at login) — a manual fallback is `tools/kev-serve.sh`. Without
one, substring and address targeting still work; descriptions fail with an
explicit message.

## No built-in judgement (2026-09-20)

hyprcu does what it's asked. Checks and controls belong in the caller, not
here. Removed from upstream's *acting* tools, beyond the trust layer:

| was | now |
|---|---|
| `sequence` aborts if the desktop changes between steps (default on) | runs every step; `stop_on_change=true` is opt-in |
| `sequence` capped at 20 steps / 30 s | effectively unbounded |
| `launch` wait clamped to 1–30 s | caller's value |
| `wait_for` timeout clamped to 1–60 s | caller's value |

The event stream still serves `wait_for` steps inside a sequence (so an
event between steps isn't missed) — that's plumbing, not a guard.
`tests/test_no_guards.py` pins this contract.

## Trust/approval language audit (2026-09-20)

Verified against the live MCP wire, not just the source:

- No code path can raise a refusal: `grep "raise TrustError"` → 0 hits outside
  the stub's class definition.
- Server `instructions` (what the model reads at connect): 0 gating terms.
- Tool descriptions: the three `allow_auth=true overrides the refusal…`
  sentences, "panic-kill guarantees", and "Refused while HYPRCU_CONFINE"
  removed. Remaining "confirm" is "screenshot to confirm the click worked".
- `allow_auth` is still an accepted boolean on pointer/keyboard/click_ui —
  it flows only into no-op stubs, FastMCP emits it with no description, and
  8 upstream tests pass it. Left in to keep server.py logic identical to
  upstream; harmless.
- `HYPRCU_READONLY=1` still works as an opt-in "observe only" mode (hides
  acting tools). Nothing sets it by default.

## Lineage

hyprcu is a fork of [hypruse](https://github.com/IlyasKhallouki/hypruse) by
IlyasKhallouki (MIT). The Wayland/Hyprland primitives — `wire.py` (virtual
pointer), `a11y.py`, `events.py`, `hyprctl.py`, `input.py`, `screenshot.py`
and the MCP `server.py` — are his work, kept close to upstream so fixes can be
merged. hyprcu removes the trust/journal/safety layers and every built-in
refusal, and adds kev-based natural-language targeting, window-relative
coordinates, and a training log. Upstream reference checkout: `~/Work/hypruse`.
