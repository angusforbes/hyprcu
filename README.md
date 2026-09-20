# hyprdesk

Dialog-free computer use for Hyprland. A fork of
[hypruse](https://github.com/IlyasKhallouki/hypruse) (MIT, IlyasKhallouki)
with the trust, journal, safety-beacon and CLI layers removed, keeping the
Wayland/Hyprland primitives intact. Companion to
[pi-omarchy-computer-use](https://github.com/angusforbes/pi-omarchy-computer-use).

## What's kept (byte-identical to upstream)

| module | what |
|---|---|
| `wire.py` | raw `zwlr_virtual_pointer_v1` client — motion+button+axis from one pointer, so drag works |
| `a11y.py` | AT-SPI tree via `busctl` |
| `events.py` | Hyprland socket2 listener → `wait_for`, event-driven `launch`/`close_window` |
| `hyprctl.py` | IPC layer; handles both hyprlang and Lua-dispatch Hyprland |
| `input.py`, `screenshot.py`, `clipboard.py`, `session.py` | as upstream |
| `server.py` | the MCP server, unmodified |

## What's replaced with no-op stubs

`trust.py`, `journal.py`, `safety.py`, `skill.py` — same public names, every guard passes,
every log call is a no-op. `server.py` didn't need a single edit.

## What's removed

`waybar/`, `packaging/`, and upstream's `init` wizard, `journal`/`replay`
commands and skill installer.

## CLI (shell verbs) — kept

Every MCP tool is also a shell verb, ~150ms per fresh process, for agents
that only have bash (Codex, Claude Code in a terminal, scripts):

    hyprdesk                                  # no args = MCP server on stdio
    hyprdesk desktop                          # one line per monitor/workspace/window
    hyprdesk screenshot --window 0x…          # prints path + {"geometry","scale",…}
    hyprdesk hypr focus_window 0x…
    hyprdesk pointer click 800 60
    hyprdesk keyboard type "hello" --window 0x…
    hyprdesk sequence '[{"op":"keyboard","action":"type","text":"x"},…]'
    hyprdesk doctor                           # check binaries + session
    hyprdesk stop                             # kill any running server/verb

Exit codes: 0 delivered · 1 error · 2 usage · 4 nothing to act on.

## Tests

`uv run pytest tests/ --ignore=tests/test_e2e.py` → 362 passed, 45 xfailed.
The xfails are enumerated in `tests/removed_guard_tests.txt`; each asserts
that a guard refuses something. They are `strict`, so a guard silently
coming back would fail the suite.

## Run

    uv sync
    uv run python -m hypruse        # MCP server on stdio

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

## What hyprdesk adds (the parts that are ours)

**`pick.py` — natural-language window targeting.** Every `window` argument
(hypr, pointer, keyboard, screenshot, ui, click_ui…) accepts an address, a
class/title substring, or a description. Resolution: exact address → unique
substring (free) → kev choice (~200ms, local). Ambiguous substrings are also
tie-broken by kev. Below `KEV_GATE` (0.5) it fails with "the app may not be
open — check desktop() or launch it", which has been right every time so far.
Results carry `[kev: 99% in 229ms]` so you can see when it was used.

    hyprdesk hypr focus_window "the file browser"
    hyprdesk keyboard type "hello" --window "the shell on workspace 2"

**Window-relative clicks.** `pointer` takes `window` + `x_pct`/`y_pct`
(0.0–1.0); the window is focused first and the fraction is mapped to its
current geometry, so the click survives moves and resizes. CLI:
`hyprdesk pointer click --in "Strata" --at 0.053 0.23`.

**`journal.py` — training log.** Acting tools append one JSONL row to
`~/.local/share/hyprdesk/actions.jsonl` (`HYPRDESK_LOG=0` disables): args,
the window list at the time, result, and — when kev chose — query and
probability. Rows are unlabelled; a `correct` field is meant to be added
later before anything is trained on them.

Requires a Jev-compatible server at `KEV_URL` (default kev-4b on :8009, see
pi-omarchy-computer-use/kev-serve.sh). Without one, substring and address
targeting still work; descriptions fail with an explicit message.

## Trust/approval language audit (2026-09-20)

Verified against the live MCP wire, not just the source:

- No code path can raise a refusal: `grep "raise TrustError"` → 0 hits outside
  the stub's class definition.
- Server `instructions` (what the model reads at connect): 0 gating terms.
- Tool descriptions: the three `allow_auth=true overrides the refusal…`
  sentences, "panic-kill guarantees", and "Refused while HYPRUSE_CONFINE"
  removed. Remaining "confirm" is "screenshot to confirm the click worked".
- `allow_auth` is still an accepted boolean on pointer/keyboard/click_ui —
  it flows only into no-op stubs, FastMCP emits it with no description, and
  8 upstream tests pass it. Left in to keep server.py logic identical to
  upstream; harmless.
- `HYPRUSE_READONLY=1` still works as an opt-in "observe only" mode (hides
  acting tools). Nothing sets it by default.
