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

`trust.py`, `journal.py`, `safety.py` — same public names, every guard passes,
every log call is a no-op. `server.py` didn't need a single edit.

## What's removed

`cli.py`, `verbs.py`, `skill.py`, `cli_state.py`, `waybar/`, `packaging/`.

## Tests

`uv run pytest tests/ --ignore=tests/test_e2e.py` → 320 passed, 32 xfailed.
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
