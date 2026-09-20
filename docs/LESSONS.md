# Desktop Control Lessons (Hyprland / Wayland)

Hard-won notes from building and testing `~/.pi/agent/extensions/hyprcu (was desktop.ts)`.
**Read before any desktop automation work.**

## Current tool stack (v4, ydotool-free)

| Tool | Purpose | Speed |
|---|---|---|
| `hyprctl dispatch` | Cursor movement, focus, workspace switch, close | ~13ms |
| `wlrctl` | Clicks, scroll (Wayland virtual pointer) | ~7ms |
| `wtype` | Typing text, key combos (Wayland virtual keyboard) | ~5ms |
| `grim` | Screenshots (JPEG q90 default) | ~65ms |

No daemon. No root. No evdev. Pure Wayland.

## ydotool (DEPRECATED — kept for reference)

ydotool is no longer used in the extension. These notes are kept in case
it's needed as a fallback (e.g. for compositor keybinds that wtype can't
trigger).

- Socket: `/run/ydotoold/socket` (not the default path)
- Absolute coords: `logical / monitorScale` (NOT logical, NOT physical)
- Click codes: `0xC0`=left, `0xC1`=right, `0xC2`=middle
- Scroll: `ydotool mousemove --wheel -x 0 -y N`
- Type: `ydotool type -d 30 "text"`
- Key combos: `ydotool key 29:1 46:1 46:0 29:0` (Ctrl+C)
- SUPER key (evdev 125) works at compositor level — wtype cannot trigger
  compositor binds (SUPER+N etc). But `hyprctl dispatch` can switch
  workspaces directly, so ydotool is not needed for this either.

## 1. Hyprland 0.56+ Lua dispatch

The old `hyprctl dispatch focuswindow address:0xABC` is **DEAD**.
Everything now goes through `hyprctl eval` with Lua tables:

```bash
# Focus a window
hyprctl eval 'hl.dsp.focus({window = "address:0x55a67391cd20"})'

# Close a window
hyprctl eval 'hl.dsp.window.close({window = "address:0x55a67391cd20"})'

# List hl.dsp dispatchers (discovery trick)
hyprctl eval 'local s="" for k,_ in pairs(hl.dsp) do s=s..k.."," end error(s)'
```

### Available hl.dsp namespaces (v0.56.2)
```
focus, window, workspace, exec_cmd, cursor, group, submap,
force_idle, exit, force_renderer_reload, event, exec_raw,
layout, pass, dpms, send_key_state, send_shortcut, no_op,
global, release_input_capture
```

### hl.dsp.window methods
```
set_prop, center, move, swap, cycle_next, drag, deny_from_group,
toggle_swallow, pseudo, tag, float, alter_zorder, fullscreen_state,
kill, signal, pin, fullscreen, close, clear_tags, bring_to_top, resize
```

### Workspace switching
`hl.dsp.workspace` only has: `change_id, move, toggle_special, swap_monitors, rename`.
No "go to" — use keyboard shortcut instead:
```bash
# SUPER+3 to switch to workspace 3
ydotool key 125:1 4:1 4:0 125:0
```

### Discovering any hl table
```bash
hyprctl eval 'local s="" for k,_ in pairs(hl) do s=s..k.."," end error(s)'
```

## 2. wtype limitations

wtype is a **virtual keyboard** — it cannot trigger:
- **Compositor keybinds** (SUPER+N, SUPER+Q etc) — use `hyprctl dispatch`
- **Terminal emulator keybinds** (Ctrl+Shift+V paste, Ctrl+Shift+C copy) —
  these are handled by the terminal app before the Wayland keyboard protocol.
  Workaround: use `wl-paste` to read clipboard and `wtype` the content directly.
  Or fall back to ydotool for Ctrl+Shift+V (evdev level triggers them).

```bash
# Instead of trying to paste:
FILEPATH=$(wl-paste)
wtype "open '${FILEPATH}'"
```

## 3. wtype modifier names

Lowercase strings only: `ctrl`, `alt`, `shift`, `logo` (for Super), `altgr`, `capslock`, `win`.
NOT `Control_L`, `Alt_L`, etc. Those are xdotool names.

```bash
wtype -M ctrl -k a -m ctrl    # Ctrl+A
wtype -M ctrl -M shift -k v -m shift -m ctrl   # Ctrl+Shift+V
```

## 3. grim screenshots

```bash
grim -s 1 -g "x,y WxH" -t png /tmp/out.png
```
- `-s 1` forces 1× scale (without it, a 2× display gives 2× resolution images — huge)
- Geometry uses **logical** coordinates (Hyprland layout coords)
- `-t png` or `-t jpeg -q 80`

## 4. Strata file browser (io.github.lgse.Strata) — app profile

**Launch:** `nohup strata &` — `hl.dsp.exec_cmd` silently did nothing twice.
hyprcu `launch -- strata` works (event-driven, ~170ms to address).
Opens half-size in `special:reprieve`; move to a workspace and
`hypr fullscreen` to get the full 1416×850 layout the geometry below assumes.
**kev:** "the file browser" / "the file manager" → 99–100%.

**Layout (fullscreen, fractions of window):**
- Sidebar x≈0.053. Rows: Home 0.078, Trash 0.123, Network 0.168,
  Documents 0.230, Downloads 0.275, Pictures 0.320, Videos 0.365,
  Projects 0.450, Work 0.495. Hover shows a path tooltip.
- File list column x≈0.21–0.35; first row y≈0.117, row pitch ≈0.033.
  Folders show `>` at the right edge (x≈0.35).
- Footer (y≈0.98) lists the live keymap — read it before guessing.

**Keys (from footer):** ↑↓ navigate · Enter open · Space preview ·
Ctrl+F filter · **Ctrl+C / Ctrl+X copy / cut** (Ctrl+C on a file puts its
full path on the clipboard — verify with `wl-paste`) · Del trash · F1 shortcuts.
Right-click → context menu: Open, Open With…, Quick preview, Print, Cut,
Copy, **Copy path (Y)**, Copy name, **Move to…, Copy to…**, Rename,
Compress…, Customize…, Properties, Move to Trash, Permanently delete.

**Pointer behaviour:**
- Single click selects; Enter opens. Double-click is unreliable for folders.
- **Press-and-drag across rows = rubber-band sweep-select**, NOT drag-and-drop.
  Verified with hyprcu's unified pointer (mid-drag screenshot shows every
  swept row highlighted). Strata has no row DnD; move files via
  "Move to…" or Ctrl+X → navigate → Ctrl+V.
- Sidebar can scroll: if only DEVICES is visible, the nav items are above.

**a11y:** exposes 1 AT-SPI element (the sidebar toggle). The file list is
custom-drawn — `ui`/`click_ui` are useless here; use fractions above.

## 5. Pi extension image return format

Tool-result image blocks are **flat**, per `docs/session-format.md`:
```typescript
{ type: "image", data: base64String, mimeType: "image/jpeg" }
```
NOT `{type:"image", source:{type:"base64", mediaType, data}}` — that's the
Anthropic wire format, and it's what `docs/extensions.md` line ~1450 shows for
`sendUserMessage`, which is misleading. Using it in a tool result throws
`The first argument must be of type string, Buffer...` deep in pi's
attachment handling. Cost two separate debugging sessions.

## 6. Running input from pi's bash

When pi runs ydotool/wtype commands via bash, focus timing matters:
- **wtype** types into the Wayland-focused window. If pi's terminal has focus,
  text goes there instead of the target. Use ydotool type for cross-window.
- **ydotool type** works at evdev level — types into whatever has keyboard
  focus at the kernel level. More reliable for automation.
- For complex sequences, write a shell script and run via `nohup` in background
  to avoid pi's terminal intercepting keystrokes or timing out.

## 7. Pi TUI input area

Pi's editor input widget is NOT a standard terminal text area. You cannot:
- Mouse-select text in it with triple-click
- Copy from it with Ctrl+Shift+C
Use the filesystem or wl-copy/wl-paste for clipboard operations instead.

## 8. Workspace switching — three methods

**Fastest (preferred):** `hyprctl dispatch` with Lua focus:
```bash
hyprctl dispatch 'hl.dsp.focus({workspace = "3"})'
```
~13ms, no external tool needed.

**Alternative — top bar click:** The top-left of the omarchy bar shows workspace
numbers (1, 2, 3…). The active workspace has a square covering its number.
Clicking a number switches workspaces. Useful if you're already moving the
cursor near the bar. Logical coords: roughly y=8, x varies by workspace number
(~25px spacing starting around x=25).

**Fallback — ydotool SUPER+N:** evdev keycodes (SUPER=125, 1=2, 2=3, 3=4…).
Works but requires ydotoold daemon. Not needed anymore.

## 9. Resolution

If desktop interactions are failing due to resolution/scaling issues, you are
**authorized to increase the monitor resolution**. Use:
```bash
hyprctl keyword monitor eDP-1,2880x1800@60,0x0,1   # scale 1 = full res
hyprctl keyword monitor eDP-1,2880x1800@60,0x0,1.5  # scale 1.5
hyprctl keyword monitor eDP-1,2880x1800@60,0x0,2    # scale 2 (default)
```
Lower scale = more logical pixels = more room = easier targeting.
Higher scale = bigger UI elements = easier to read in screenshots.
Current: scale 2 (logical 1440×900).

## 10. hypruse approach — better mouse input (future improvement)

hypruse (https://github.com/IlyasKhallouki/hypruse) avoids ydotool entirely:
- **Cursor positioning**: `hyprctl dispatch movecursor X Y` — uses the compositor's
  own cursor dispatcher with global logical coordinates. No coordinate translation
  needed, no multi-monitor bugs.
- **Clicks/scroll**: raw Wayland `zwlr_virtual_pointer_v1` wire protocol — sends
  button/axis events as a native Wayland client. No daemon, no root, no evdev.
- **Keyboard**: still uses `wtype` (same as us), which is the right tool.

This is superior because:
1. No ydotoold daemon dependency
2. Coordinates are plain Hyprland logical coords (no `logical/scale` math)
3. Works on any keyboard layout (wtype uses real XKB keymap)
4. Sidesteps multi-monitor absolute positioning bugs
   (https://github.com/hyprwm/Hyprland/issues/6749)

Consider migrating pointer input from ydotool to `hyprctl dispatch movecursor`
+ a small Wayland virtual-pointer client for clicks. Or just use hypruse as
an MCP server alongside the extension.

## 11. Full-desktop screenshot

```bash
grim -s 1 -g "0,0 1440x900" -t png /tmp/full-desktop.png
```
Uses logical resolution (1440×900 on this machine). Useful for seeing the
complete layout including tab bars, workspace indicators, etc.

## 12. Window addresses go stale — never cache them

Hyprland window addresses are heap pointers. When the user closes and
reopens an app, the address changes. Terminal `0x55a673286d30` became
`0x561283a7ce40` after a close/reopen. **Always re-query `hyprctl clients -j`
at the start of each action sequence.** Never hardcode or carry addresses
across turns.

Also: windows move between workspaces. The terminal was on ws1, then ws2.
Query by class+title, not by remembered workspace.

## 13. Percentages vs anchored offsets

Window-relative percentages (x_pct/y_pct) work for **layout that scales with
the window** (a webpage that reflows, a maximized app). They **break** for
fixed-size elements centered in a variable-width container.

Google's tic-tac-toe grid is a fixed 210×210px square inside a 650px-wide
results card. At window width 1416 the card is at x=150; at 701 it's at x=8.
The grid center moves, but the cell spacing (70px) does not.

**Pattern:** find a locatable anchor (card center, a known button), then use
fixed pixel offsets from it. `ttt.sh` does: `grid_center()` → `cx + (col-2)*70`.

## 14. Idle inhibitor for long test runs

`systemd-inhibit --what=idle --who=Grip --why="testing" --mode=block sleep 1800 &`
Blocks the screensaver for 30 min. `movecursor` dispatches also count as
activity, but long think-pauses between actions can trigger idle.

## 15. Google Tic-Tac-Toe (Medium) — solved

The Medium AI is deterministic. Winning sequence as X (0-indexed r,c):
1. [2,2] center → O plays [2,3]
2. [1,1] corner → O plays [3,3]
3. [1,3] block → O plays [3,1]
4. [1,2] → **X wins top row**

~0.9s between moves is the minimum; 0.7s and the second click is swallowed
by O's animation. 4 moves ≈ 3.5s blind. `ttt.sh` has the full flow.

## 16. Fast tic-tac-toe: pixel reader + minimax (ttt_fast.py)

`ttt_fast.py --no-model` plays a full game in **5.1s with zero LLM calls**:
- grim crop of board: 40ms
- pixel-sample 9 cells (ring of 12 points at r=18 + center + diagonals): <5ms
- minimax: 0-4ms
- click via ttt.sh: 240ms
- wait for O's animation: 900ms
Per turn ≈ 280ms + 900ms wait.

**O is a hollow ring** — sampling only the cell center reads teal (empty).
Must sample a ring of points at the O's radius. Cost me a 2,300-iteration
infinite loop before I added `max_turns` and stale-board detection.

**Always guard autonomous loops**: max iterations + "did the state change
after my action?" check. If not, screenshot and bail.

## 17. OpenDecision is the wrong tool for game moves

OpenDecision (ModernBERT-large zero-shot NLI, ~400M):
- GPU first call: **61s** (triton JIT). Warm: **80ms**. CPU: **8s/call**.
- Picked the wrong tic-tac-toe cell every time, even with "(WINS immediately)"
  in the option text. It's text-similarity, not reasoning.

Use it for **classification** ("which window is the file browser?", "is this
a dialog or a page?"), not for anything needing lookahead. For deterministic
games, compute the move; for judgment, use Claude.

## 18. OpenDecision for window selection — also wrong tool

Tried `window_pick.py`: describe each open window as text, ask OpenDecision
"which matches the user's request?". Results on 6 open windows:

| Query | OpenDecision | Correct? |
|---|---|---|
| "Claude Code" | tie 0.31 between "Claude Code" and "tictactoe" | ✗ |
| "the tic tac toe game" | ranked "tictactoe" 3rd at 0.15, behind two terminals | ✗ |
| "the AI agent pane" | NONE (0.32) | ✗ |
| "a terminal" | foot ✓ | ✓ |

Near-uniform ~0.31 across options = the model can't discriminate. It's an
NLI model (premise entails hypothesis?) trained on full sentences; short
labels, proper nouns, and concatenated tokens ("tictactoe") defeat it.

A 20-line token-overlap matcher beat it on 2 of 4 hard cases at 0.1ms.

**Conclusion:** zero-shot NLI ≠ decision model. For "pick from N labeled
options", either compute it (string match, minimax) or use something trained
for calibrated choice (Jev/RLCD). Cold start (61s GPU triton JIT) also
makes OpenDecision impractical as an on-demand sidecar.

Next: try Jev API on the same window_pick queries. If it nails them, wire it
in behind a confidence gate; below the gate, fall through to Claude.

## 19. kev-4b: the fast model that actually works (window selection 9/9)

[kev](https://github.com/jaredpalmer/kev) = Qwen3 + LoRA + pointer head, trained
supervised on choice-from-options. Jev-compatible `/v1/systemone`. Local.

| model | window-pick accuracy | warm latency | VRAM | notes |
|---|---|---|---|---|
| OpenDecision (NLI) | ~30% | 80ms | 1.5GB | near-uniform probs, 61s cold start |
| kev-0.6b fp32 | 5/8 | 77ms | 1.5GB | overconfident on wrong answers |
| **kev-4b NF4** | **9/9** | **173ms** | **3.6GB** | well-calibrated: matches 0.57–1.0, non-matches 0.26–0.43 |

**Setup gotchas (cost ~1 hour):**
- `HF_HUB_DISABLE_XET=1` — hf-xet transfer backend hangs silently with zero output.
  Every HF download on this machine needs it.
- kev-4b bf16 = 7.45GB, OOMs on the 8GB card by 48MB. Patched kev to support
  `KEV_QUANT=nf4` (bitsandbytes 4-bit): 3.6GB, loads in 60s. Patch is in
  ~/Work/kev (model.py + evaluate.py), 12 lines. Should upstream.
- `pgrep -f "kev.serve"` matches your own bash -c wrapper. Use
  `ps aux | grep "[m] kev.serve" | grep -v "bash -c"`. I spent 20 minutes
  debugging a "hung server" that was my own diagnostic shell.
- Launch via a script file with `nohup script.sh > log &`. Inline
  `nohup VAR=x cmd &` and `setsid` both lost env/redirects in this harness.

**Do NOT add an explicit "none of these" option.** Both sizes treat it as a
probability sink and start refusing real matches (4b: 9/9 → 6/9). Instead use
the calibration: gate at p ≥ 0.5, fall through to Claude below it. Below-gate
is also the signal that the app may need launching.

Start: `./kev-serve.sh` (in this repo). Bench: `python3 kev_bench.py`.

## 20. Drag-and-drop (T16) — resolved

hyprcu's `pointer drag` (single `zwlr_virtual_pointer_v1` client for
press+motion+release) delivers a real drag gesture. The morning failure was
the split-device stack (ydotool button + hyprctl motion). The remaining
"failure" is app-side: Strata implements sweep-select, not row DnD — see the
Strata profile (§4). Retest DnD on an app with drop targets.

## 21. kev gate: 50% is right, but similar-titled windows can clear it wrongly

"the agent discussing Heeler" → kev picked "Claude Code" at 57% over "Heeler
app not seeing herdr app" (two `org.omarchy.agent` panes). "the Heeler app
conversation" → 86% correct. Inference ("discussing X") is weaker than
keyword presence ("X app"). When two windows share a class, keep a
distinguishing title word in the query. When two windows share a *title*
(two Chromiums both on "tictactoe - Google Search"), no model can pick —
use `window_address`.

Also: `hl.dsp.exec_cmd({cmd="strata"})` silently did nothing twice;
`nohup strata &` from bash worked. And `timeout N app &` for a GUI app kills
it after N seconds — obvious in hindsight, cost a confused minute.
Screensaver: `omarchy toggle screensaver` is the native way, not systemd-inhibit.

## 21b. Chromium (class `chromium`) — app profile

**Launch:** `chromium` — single-instance: a second launch opens a window in
the existing process (so `launch` may return an existing address).
Title: `"<page title> - Chromium"`. **kev:** describe by page content
("the browser on omarchy.org", "the tab about screen timeout") → 65–100%.
"chromium" alone is ambiguous when several windows are open → pass an address.

**Layout (fractions of window, any size):**
- Tab strip y≈0.024; tabs ~0.055 wide starting x≈0.03 (in a 701-wide
  window ~18 tabs fit, titles truncated to 3–4 chars — the favicon is the
  only reliable identifier). New-tab `+` right after the last tab.
- Address bar y≈0.073, x 0.11–0.85. Bookmarks bar y≈0.117.
- Page content starts y≈0.15.

**Keys (all work via wtype):** `Ctrl+T` new tab · `Ctrl+L` focus address bar
· `Ctrl+W` close tab · `Ctrl+Tab`/`Ctrl+Shift+Tab` next/prev tab ·
`Ctrl+1..8` tab N, `Ctrl+9` last · `Home`/`End` page top/bottom ·
`Page_Up/Down` · `/` focuses search on Google/GitHub pages · `Escape`.

**Pointer:**
- **First click on a tab often only shows the hover preview** (thumbnail
  card, "Memory usage: NNN MB") instead of switching. Click again, or use
  `Ctrl+N`. Prefer keyboard for tab switching.
- Wheel scroll is smooth and reliable (unlike Slack): ~60px per notch.
- Right-click on page gives the standard menu; on a tab gives tab menu.

**Verification:** window title changes on navigation — `wait_for
title_change --match <word>` is the reliable "page loaded" signal
(T10: 1.2s; T13: fired on both "GitHub" and "search"). Don't sleep.

**Two Chromiums, same title** (both on a Google search) is common here —
kev cannot separate them; use `desktop` and pass the address.

**a11y:** 0 elements without `--force-renderer-accessibility` at launch.

## 22. vibezAI (foot terminal titled "vibezAI-player") — app profile

**Launch:** `nohup foot --title vibezAI-player -e vibezAI &` — a Go TUI inside
a terminal, so its window class is `foot`; target it by title.
Move to a workspace + `hypr fullscreen` for the two-column layout.
**kev:** "the vibezAI music player" → 44% when NOT running (correct: below
gate); by title substring "vibezAI" once it is.

**Layout:** Now Playing bar top · **Tracks** column left · **Search** column
right · live keymap footer (bottom, y≈0.94). Search sources cycle with
`Ctrl+/`: AM (Apple Music) → AI (Claude plans terms) → SV (saved) → FE (recs).

**Keys:**
- Search: `Ctrl+'` start typing · text · `Enter` runs AM search ·
  `Ctrl+↑/↓` move highlight · `→` open/fold section · `Ctrl+→` toggle select ·
  `Ctrl+,` add to Tracks · **`Ctrl+.` add and play** · `Tab` back to Tracks.
- Tracks: `space` play/pause · `n`/`p` next/prev · `T` insert 5 random
  library songs after highlight · `R` 5 related · `c` clear · `:q` quit.
- wtype names: `-k apostrophe` for `'`, `-k period` for `.`, `-k slash`.

**Gotchas:**
- Every visible row in Search is a highlight stop — section headers
  (Playlists/Albums/Tracks), "+ 5 more", "- 5 less" all count. Albums are one
  row despite two display lines. Count from a screenshot; don't guess.
- `Ctrl+.` on a section header does nothing — land on an item.
- After `T`, Now Playing shows "⏳ Picking songs from your library…" for
  3–5s; the Tracks count updates when done.
- No in-app volume. Audio is a PipeWire stream named **"Google Chrome"**
  (headless Chrome). Set volume with `wpctl set-volume @DEFAULT_AUDIO_SINK@
  25%` or the bar's audio widget (§23).

## 23. Omarchy bar — Audio widget (omarchy.audio) — app profile

Click the icon to open a panel at screen ≈(1057–1440, 30–430):
- Mute toggle: switch at ≈(1395, 65). Label under "Audio" reads MUTED/MURMUR/
  etc. The label can lag — **verify with `wpctl get-volume @DEFAULT_AUDIO_SINK@`**
  after every click, don't trust the picture.
- OUTPUT slider: track ≈ x 1077→1412 at y≈147. Clicking at a point sets that
  fraction directly (25% → x=1161). Worked first try.
- Per-app SOURCES section with its own sliders — this is how a single app
  (e.g. Chromium) ends up muted while the sink is fine.
- `Escape` closes it.

## 24. Slack (class `slack`) — app profile

**Launch:** `slack` (Electron). Title: `"<Person> (DM) - <Workspace> - Slack"`
or `"<Channel> ... - Slack"`. **kev:** "slack" → 100% when open, 37% when not.

**Navigation — use the keyboard, not the sidebar:**
- **`Ctrl+K`** → type a name → `Enter` opens that DM/channel. First result is
  the 1:1; group DMs listed below. Far faster than hunting the sidebar.
- **`Ctrl+F`** opens "Search messages in this channel".
- **Scrolling the message pane by wheel is unreliable**: slow steps move
  ~4px, fast steps accelerate and overshoot by weeks, and it snaps to the
  latest message on overshoot. **Click in the message pane, then use
  `Page_Up`/`Page_Down`** — deterministic, one screen per press.
- Sticky date header ("Wednesday, September 16th ▾", x≈0.63 y≈0.17) names
  the day of the top visible message. Use it to know where you are.

**Content:**
- Inline links render as `🔗 domain` chips; the chip is the reliable click
  target (the unfurl card below is also clickable). Clicking opens the
  default browser, reusing an existing Chromium window and switching its
  active tab — verify by the window title changing.
- Image attachments: hover the thumbnail → toolbar at its top-right:
  **⬇ download** then ⋮. Download saves to `~/Downloads/<original-name>`
  with **no dialog**. Verify: `ls -t ~/Downloads | head -1`.
- Date dividers are real DOM rows; scroll to one to find a day's first message.

**a11y:** 0 AT-SPI elements without `--force-renderer-accessibility`.
Vision + fractions only.


## 25. Long-running servers must NOT be started from the agent's bash tool

Symptom: kev server "shuts down cleanly" 2 requests after start, port left
half-held, `pick.py` reports "kev unreachable". Repeated 4×.

Causes, both self-inflicted:
1. `nohup cmd > log 2>&1 &` inside pi's bash: the child is in the tool's
   process group and is HUP'd/killed when the tool call returns. `setsid -f`
   helped but not reliably.
2. `pkill -f "kev.serve"` in a diagnostic matches the `bash -c "…kev.serve…"`
   wrapper of the *current* command AND any fresh server. I killed the thing
   I was checking on, then concluded it was flaky.

Fix: run servers in a **persistent Herdr subagent pane** (`subagent` tool,
`persistent: true`), or a systemd user unit. Never from a one-shot bash call.
`pgrep -f` with a pattern that can match your own shell: use `[k]ev.serve`
or `pgrep -f "python3 -u -m kev.serve"` (full argv, no wrapper match).

## 26. kev NF4 patch: move the pointer head to GPU too

`KEV_QUANT=nf4` left `m.head` (PointerHead) on CPU/fp32 because the
non-quantized path moved it via `m.lm.to(dev)` and the quantized branch
skipped that. Every call shipped hidden states GPU→CPU: **4.5 s per call,
linear in option count (~330 ms/option)**, GPU at 100% the whole time.
Fix in `~/Work/kev/kev/evaluate.py`: `m.head.to(dev).to(dtype)` in the
quantized branch, and cast LoRA params to `dtype`. Expected: ~200 ms.
Diagnostic that found it: same query at 2/6/13 options → 1.0/2.2/4.4 s.

## 27. Screen off → grim hangs → stale screenshots

`dpms: False` (display powered off by idle) makes wlr-screencopy block; grim
hits its 10s timeout and returns nothing, or a *previous* frame. T22 read a
finished board and declared "O wins in 0 moves". Now: `desktop()` shows
`display off`, `screenshot` errors immediately with the fix, and
`hypr dpms_on` wakes it. Keep an inhibitor running during long sessions —
detached (`setsid -f systemd-inhibit …`), not from a one-shot bash call.
