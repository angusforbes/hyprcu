# Architecture

Ten-minute orientation for contributors.

A fork of [hypruse](https://github.com/IlyasKhallouki/hypruse) (MIT,
IlyasKhallouki): the Wayland/Hyprland primitives are kept close to
upstream so fixes merge cleanly, the trust/journal/safety/CLI layers that
*dictate what an agent may do* are replaced with no-op stubs or strapped
down, and three capabilities are added (natural-language window targeting,
window-relative coordinates, and a training log). The README's
"kept / replaced / removed" tables are the authoritative picture; this
file explains how the pieces fit.

## Module map

```
src/hyprcu/
  cli.py         entry point: no args → MCP stdio server; --help/--version;
                 bare verbs route to verbs.py. doctor + stop are the only
                 owner commands (init / journal / replay / skill are no-op
                 stubs that print "removed")
  verbs.py       the 14 tools as shell verbs: argparse over the same tool
                 functions, the output and exit-code contract, renderers,
                 and the cross-process acting lock in cli.lock
  cli_state.py   what a one-shot verb remembers between processes (marks
                 numbering, the owned-set, the seat baseline), keyed by
                 compositor instance — a verb is a fresh process per call
  pick.py        hyprcu's NAMED capability: address → substring → kev
                 natural-language window resolution (see below)
  journal.py     hyprcu's training log: NDJSON rows of acting calls with
                 the kev query + probability, written best-effort to
                 ~/.local/share/hyprcu/actions.jsonl (HYPRCU_LOG)
  server.py      the 14 tools (clipboard opt-in); docstrings = the
                 agent-facing API; the FastMCP app is built on first use
  hyprctl.py     all Hyprland IPC (queries + dispatchers), the config-manager
                 probe and the Lua dialect, state trimming, SESSION_LOCKED
                 observation, keybind decoding
  events.py      socket2 event stream: parser + wait primitive
  wire.py        raw Wayland client for zwlr_virtual_pointer_v1
  input.py       pointer orchestration (movecursor + wire) and wtype keyboard
  screenshot.py  grim capture: monitor / window / region + coord metadata
  a11y.py        AT-SPI accessibility-tree reader over D-Bus (busctl): named
                 controls, current values, exact coords; backs ui, marks,
                 click_ui, then='ui'
  clipboard.py   wl-clipboard wrapper for the opt-in clipboard tool
  session.py     discovers HYPRLAND_INSTANCE_SIGNATURE / WAYLAND_DISPLAY
                 from runtime-dir sockets when the host stripped the env
  cleanup.py     process-exit handlers (SIGTERM + atexit): the server and
                 verbs register `input.release_held` here so a kill
                 mid-drag releases the button instead of stranding it
  trust.py       no-op stub — same public names as upstream, every guard
                 passes, nothing refuses (see "No built-in judgement")
  safety.py      no-op stub — no activity beacon; `pkill -f hyprcu` is the
                 kill switch
  skill.py       no-op stub — no skill installer
```

Rule of thumb: `server.py` validates and narrates; everything real happens
in the leaf modules, which stay importable and testable without MCP. The
three stubs exist only so `server.py` and `input.py` need no edits — their
calls still resolve.

## Two surfaces, one set of tools

The MCP server and the shell verbs call the same module-level functions in
`server.py`, so a journal row or a window-resolution is written once. What
differs is transport. A tool returns either a string or a list of content
blocks, and it asks for those blocks through `_text()`/`_image()` rather
than naming `mcp.types`: the MCP path gets the pydantic objects FastMCP
expects, the CLI path (`use_plain_blocks()`) gets a plain `Block` with the
same fields. That, plus building the FastMCP app on first access
(`app()`, reachable as `server.mcp`) instead of at import, is what keeps
a verb's startup cheap: importing the MCP stack costs about two seconds of
pydantic model building, which a process that only prints text and file
paths must not pay. (Measured: the installed `hyprcu` binary starts in
~20 ms cold; the 150–300 ms figure in older docs is the `uv run …` path.)

The CLI adds two things the server does not need. `cli_state.py` carries
across processes what a long-lived server keeps in memory: the `marks`
numbering and the `owned`/seat baseline. It is keyed by compositor
instance, since window addresses are heap pointers, and every consumer
degrades to "nothing remembered" rather than guessing. An *acting* verb
(any tool in `ACT`) takes a cross-process lock (`cli.lock`, held for the
process's lifetime) and stamps its journal rows `source: "cli"`, the same
serialization the server gets from an in-process lock, so two parallel
verbs can't interleave a drag's press and release on the one virtual
pointer.

## The coordinate contract

One space rules everything: **Hyprland global logical coordinates** (what
`hyprctl cursorpos`, client `at`, and cursor positioning speak).

- `desktop` reports window geometry in it.
- `pointer` accepts it.
- `screenshot` captures *pixels* and returns `geometry` + `scale` per
  capture so callers map back: `global = origin + pixel / scale`.

If you touch anything coordinate-adjacent, preserve this contract; it is
what keeps multi-monitor and fractional scaling tractable. On top of it,
two of hyprcu's additions live: **window-relative pointers** (`pointer` /
`drag` take an optional `window` plus `x_pct`/`y_pct` in 0–1, resolved
against that window's *current* geometry after focusing it, so a click
survives a move or resize) and **window-relative a11y marks** (`click_ui
--mark N` numbers are stored window-relative).

## Natural-language window targeting (pick.py)

Every `window=` argument on hypr, pointer, keyboard, screenshot, ui and
click_ui accepts, in order:

1. an exact address (`0x…`) — no resolution cost, the only form kev can't
   improve on;
2. a unique class/title substring — free, no model call;
3. a natural-language description ("the file browser"). This goes to
   **kev-4b**, a local Jev-compatible decision model, which scores the
   open windows; below `KEV_GATE` (0.5) `resolve()` raises an actionable
   "the app may not be open — check desktop() or launch it" instead of
   guessing. When kev is unreachable at `KEV_URL`, substrings and
   addresses still work and descriptions fail with an explicit message.

Ambiguous substrings are tie-broken by the same kev call restricted to the
matching windows, accepting the winner when its margin over the runner-up
is clear even if the absolute score is below the gate. A result that kev
chose carries a note like `[kev: 99% in 229ms]` so callers can see when
the model was used. `tools/kev_bench.py` is the honesty check against
ground-truth cases.

## The two config managers

Hyprland 0.56 added a Lua config manager beside the original hyprlang one
and picks between them by the config file's extension, so a session runs
one or the other and no version check can tell you which. The choice
reaches the IPC, not just the config file: under the Lua manager `hyprctl
dispatch X` evaluates the Lua expression `hl.dispatch(X)`, so every legacy
dispatcher string is a syntax error, and `hyprctl keyword` is refused
outright.

`hyprctl.provider()` probes it once with `-j status` and caches the answer;
`dispatch()` translates the legacy call into the `hl.dsp.*` expression that
lands on the same compositor action, and re-probes if a call fails, since
`hyprctl reload full-reset` can change the manager under a running server.
Callers upstack never see the difference, which is the point: a window op
is described once.

Two things the Lua manager takes away rather than renames. `use_bind`
cannot run a bind, because a Lua config binds an anonymous closure that
Hyprland exposes no IPC route to call; `binds` still reports the combo and
description, and `use_bind` refuses with that explanation instead of a
parser error. And a runtime window rule becomes `hl.window_rule` rather
than a keyword, which is what `border_rule()` exists to hide.

Everything the Lua path sends is built by `lua_str()` and the `_lua_*`
builders. That is a security boundary, not formatting: `hyprctl dispatch`
hands its argument to the compositor's interpreter as an expression with
the standard library open, so an argument that is not a literal is code
running inside the compositor.

## Why input works the way it does

- **Position** via the compositor's own cursor dispatcher (`movecursor` on
  hyprlang, `hl.dsp.cursor.move` on Lua), authoritative, global, no
  per-monitor extent math, immune to
  [hyprwm/Hyprland#6749](https://github.com/hyprwm/Hyprland/issues/6749).
  On a named seat it goes over the wire instead, because that dispatcher
  moves the one cursor the human owns.
- **Buttons/axis** via a virtual pointer created over the raw wire
  (`wire.py` is ~250 lines: registry scan, bind, button/axis/frame, sync
  barrier, wl_display.error surfacing). No daemon, no uinput, no root.
- **Keyboard** via `wtype`: it uploads its own XKB keymap through
  `zwp_virtual_keyboard_v1`, which is why unicode and non-US layouts work.
  We shell out instead of reimplementing keymap upload; that wheel is
  round already.

A click's press and release always happen inside one tool call; a drag
holds a button across ~200 ms of cursor moves. The server and every
*acting* verb register `input.release_held` on `cleanup`, so SIGTERM (or
`pkill -f hyprcu`) runs it before the process dies and no held button is
stranded mid-drag. The cleanup is deliberately separate from the removed
`safety` beacon stubs.

## Sequence of a typical agent step

1. `desktop` → find `firefox` at `0x…`, workspace 3, geometry.
2. `hypr focus_window 0x…` (IPC, ~ms), no vision spent.
3. `screenshot window=0x…` → crop + `geometry`/`scale` (or `ui` to read
   the accessibility tree by name, no pixels).
4. `pointer click x y`, computed from image pixel via the contract (or
   `pointer click --in "Strata" --at 0.053 0.23` to target a window by
   description and fraction, or `click_ui name="Save"` to resolve and
   click in one call).
5. `keyboard type "…"`.
6. `desktop` again to verify the world changed as expected (or fuse it:
   most acting tools take `then='desktop'|'screenshot'|'ui'`).

## No built-in judgement

hyprcu does what it's asked. The upstream trust layer — confinement,
authenticator detection, seat-ownership, session-lock refusal — was the
part that *decides not to act*, and it is replaced by `trust.py` stubs:
every `trust.guard_*` call resolves, no `TrustError` is raised, no action
is refused. `test_no_guards.py` pins this: acting tools have no step cap,
no time budget, no clamped waits, `sequence` does not abort on desktop
change unless `stop_on_change=true` is passed, and no tool docstring
promises a refusal.

What is *kept* is the part upstream used for the agent's awareness: the
observation that the tool reports but cannot see around. `desktop` leads
its snapshot with `SESSION_LOCKED` and a note when a locker process is up
(modern lockers are `ext-session-lock-v1` clients, invisible to both
`clients` and `layers`), reports `display: off` under DPMS, and pick.py
names kev-unreachable explicitly. None of it stops the call; all of it is
meant to be read first. `HYPRCU_READONLY=1` is the opt-in that actually
removes the acting tools from the surface.

## The record: the training log

`journal.py` is the layer that *remembers* the agent's own actions for
training, and it is real (not a stub): a `@journal.journaled` decorator at
each tool's definition site appends one NDJSON row per call to
`~/.local/share/hyprcu/actions.jsonl` (`HYPRCU_LOG=0` disables). A row
carries the tool, the not-defaulted arguments, the window list at the
time, the result, and — when kev chose a window — the query and
probability. Acting tools are tagged `"act"`, observers `"observe"`.
Rows are deliberately unlabelled: a `correct` field is meant to be added
later before anything is trained on them. The recorder fails toward the
action — an unwritable journal warns on stderr and gets out of the way.

There is no `HYPRUSE_JOURNAL` audit trail, no `HYPRUSE_DRYRUN` effect
barrier, and no `hyprcu journal`/`replay` command in this fork; `--dry-run`
rehearses an acting verb but the deep upstream journal features were
removed.

## Testing tiers

1. **Unit** (CI): pure functions, wire encoders/parsers, combo parsing,
   region parsing, state trimming against fixtures, and the no-guards
   contract. `uv run pytest tests/ --ignore=tests/test_e2e.py` → 362
   passed, 53 xfailed (the xfails are enumerated guard-refusals that must
   stay removed, marked `strict` so a guard silently coming back fails the
   suite).
2. **Live seat-safe** (`pytest -m e2e`): real session, zero input events,
   including a virtual-pointer create/destroy handshake and full MCP stdio
   round-trips.
3. **Supervised** (`tools/`): the only tier that clicks and types —
   `ttt_fast.py`, `kev_bench.py`, `window_pick.py`. Never wire these into
   anything automatic; `docs/TESTS.md` records the supervised flows.

## Known gaps

- `sequence` runs its steps sequentially in-process through the same
  module-level tool functions; a step that raises stops the run (an
  error, not a guard).