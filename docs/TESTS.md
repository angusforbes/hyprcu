# Desktop Interaction Tests

> **Status note (2026-09-20, hyprcu).** The runs below are the **historical
> record of the retired `desktop.ts` extension** (and, for Run 2, the first
> hyprcu pointer against the same flows). The stack these were written for is
> gone: `desktop.ts` is retired and everything it did is in hyprcu. Today the
> relevant live tests are the CI + `/pytest -m e2e` tiers in ARCHITECTURE.md
> ("Testing tiers"), and the supervised `tools/` scripts. Under hyprcu only
> T1–T21 have been re-verified; **T22–T25 have not been rerun under hyprcu**
> (the session locked mid-run; see HANDOFF) and remain to be re-run before
> they count as current. The tables below are kept as-is for context, not as
> a claim about the current stack.

---

20 tests of increasing complexity for the `desktop` extension.
Stack: `hyprctl dispatch` + `wlrctl` + `wtype` + `grim`.

---

## Level 1 — Single actions

### Test 1: List all windows
List every open window and report their workspace, class, and title.

### Test 2: Screenshot the active window
Take a screenshot of whatever window is currently focused and describe what's on screen.

### Test 3: Focus a window by name
Find the Obsidian window and focus it, then confirm by reading the active window.

### Test 4: Type into a terminal
Focus the foot terminal on workspace 1 and type `echo "desktop control works"` then press Enter.

### Test 5: Click a specific pixel
Open the Strata file browser, click on the "Home" entry in the sidebar.

---

## Level 2 — Two-step sequences

### Test 6: Navigate a folder
In Strata, click "Documents" in the sidebar, then screenshot the file list to show its contents.

### Test 7: Switch workspace and screenshot
Switch to workspace 4 (Slack), take a cropped screenshot of just the channel list sidebar, and report what channels are visible.

### Test 8: Right-click context menu
Right-click on a file in Strata, screenshot the context menu that appears, then press Escape to close it.

### Test 9: Scroll a page
Focus the Chromium browser, scroll down 10 steps, then screenshot to show the new position.

### Test 10: Open a new tab
Focus Chromium, press Ctrl+T to open a new tab, then type a URL and press Enter.

---

## Level 3 — Multi-step workflows

### Test 11: Copy text between windows
Open a file in the terminal with `cat`, read a line from the output via screenshot, then type that line into a different terminal.

### Test 12: File browser → terminal pipeline
In Strata, navigate to ~/Work, find any .md file, copy its path, switch to a terminal, and run `wc -l <path>` to count its lines.

### Test 13: Browser form fill
Navigate to a website with a search box (e.g. GitHub), click the search field, type a query, press Enter, and screenshot the results.

### Test 14: Multi-workspace roundtrip
Start on workspace 1. Switch to workspace 5 (Obsidian), screenshot the current note title, switch to workspace 4 (Slack), screenshot the current channel, return to workspace 1. Report both findings without any intermediate screenshots sent to the model — just read them yourself.

### Test 15: Window management
Move the Chromium browser from workspace 1 to workspace 7 using hyprctl dispatch, then verify it moved by listing windows.

---

## Level 4 — Complex interactions

### Test 16: Drag and drop (if supported)
In Strata, try to drag a file from one folder to another using pointer down, move, pointer up sequence.

### Test 17: Multi-tab browser navigation
In Chromium, identify all open tabs by screenshotting the tab bar, click tab 3, screenshot its content, click tab 5, screenshot its content, then report what's in each.

### Test 18: Keyboard shortcut chain
In the terminal: Ctrl+Shift+T to open a new tab (if foot supports it), type `htop` and Enter, wait 2 seconds, press `q` to quit, then type `echo done` and Enter.

### Test 19: Read and act on screen content
Switch to Obsidian, screenshot the current note, read a heading from it, switch to a terminal, and create a new file named after that heading with `touch`.

### Test 20: Full application workflow
Open a new Chromium tab, navigate to google.com, search for "hyprland wayland compositor", screenshot the results, extract the first result title by reading the screenshot, switch to a terminal, and echo that title. Time the entire sequence and report the breakdown.

---

### Test 21: Agent-to-terminal command runner
Receive a list of shell commands from the pi agent (e.g. `uname -a`, `df -h /`, `ip addr show`). Focus a terminal on workspace 1. For each command: type it, press Enter, wait for output, screenshot just the output region, read the screenshot, and collect the results. After all commands complete, return the combined output back to the pi agent as structured text. This tests the full agent→desktop→agent feedback loop — the agent both drives the desktop and reads back from it.

### Test 22: Play tic-tac-toe on Google
Find or open a Chromium browser. Open a new tab, navigate to Google, and search for "tic-tac-toe". Google shows an interactive game widget. Play the game by clicking cells on the board — screenshot after each move to read the board state, plan the next move to win or draw (try not to lose, but no pressure). After the game ends, switch to a terminal and type an ASCII art representation of the final board state, e.g.:
```
 X | O | X
-----------
 O | X | O
-----------
 X | O | X
```
This tests vision-action loops (read board → decide → click), strategic reasoning, cross-app output, and sustained multi-turn interaction with a live web widget.

### Test 23: Music player end-to-end (vibezAI)
Open the vibezAI music player (launch it if not running). Search Apple Music for songs by Billy Idol. Pick any result and move it to the tracks list, then play it. Open the volume widget and set volume to 25%. Wait 30 seconds. Press `T` to load songs from the library, then press `n` to advance to the next song. Tests: app launch, in-app search, drag/move to a list (or the app's equivalent), a slider widget, timed wait, and app-specific keyboard shortcuts.

### Test 24: Slack — find a dated message and save its attachment
Open Slack. Find the DM conversation with Oge Marques. Navigate to the first message dated 9/16. Download the image attached to that message into ~/Downloads, then open the downloaded image. Tests: search within a chat app, scrolling/navigating by date, hovering to reveal a download control, a file-save flow, and verifying the file landed.

### Test 25: Slack — open the first link in a dated DM
Open Slack, go to the DM with Johan Barthelemy, find the messages from Sept 16, and open the first hyperlink in that day's conversation in the browser. Tests: navigating a *different* DM (not the one already open), locating a date divider that may be scrolled away, distinguishing a link from plain text, and cross-app handoff to the browser.

---

## Scoring

| Grade | Criteria |
|---|---|
| ✅ Pass | Correct result, no retries needed |
| ⚡ Fast pass | Pass in under 2 seconds (excluding model thinking time) |
| 🔁 Retry | Needed a screenshot mid-flow to correct course |
| ❌ Fail | Wrong result or couldn't complete |

## Notes

- Tests assume the current window layout (Strata on ws3, Chromium on ws1/ws7, Obsidian on ws5, Slack on ws4, terminals on ws1)
- Window addresses will need to be resolved at test time via `hyprctl clients -j`
- The `wl-paste` + `wtype` pattern should be used instead of Ctrl+Shift+V for pasting
- Crop screenshots to the smallest useful region

---

## Run 2 — 2026-09-19, `desktop` tool + kev-4b window selection

| # | Test | Result | kev used | Notes |
|---|---|---|---|---|
| 1 | List windows | ✅ | – | |
| 2 | Screenshot active | ✅ | – | needed image-format fix (Lesson 5) |
| 3 | Focus by description | ✅ | 98% / 231ms | "the google tic-tac-toe tab" |
| 4 | Type into terminal | ✅ | 76% | "the shell on workspace 2" |
| 5 | Click at pct | ✅ | – | x_pct/y_pct needed a fix — was silently hitting center |
| 6 | Navigate folder | ✅ | 99% | Strata launched via nohup; `hl.dsp.exec_cmd` did nothing |
| 7 | Workspace + screenshot | ✅ | – | |
| 8 | Right-click menu | ✅ | – | full Strata context menu |
| 9 | Scroll page | ✅ | – | needed window_address: two Chromiums, identical titles |
| 10 | New tab | ✅ | – | Ctrl+T via wtype |
| 11 | Cross-window read→type | ✅ | 78% | hostname+uptime → Google |
| 12 | File → terminal | ✅ | – | wc -l on repo .md files |
| 13 | Browser form fill | ✅ | – | GitHub repo search |
| 14 | Multi-workspace roundtrip | ✅ | 100/57/86% | one wrong pick at 57% — see Lesson 21 |
| 15 | Window management | ✅ | – | move ws3→ws4→ws3 |
| 16 | Drag and drop | 🔁 | – | hyprcu pointer ✓ (sweep-select seen mid-drag); Strata has no row DnD |
| 17 | Multi-tab navigation | ✅ | – | Chromium hover-preview ate first click |
| 18 | Keyboard chain | ✅ | 78% | |
| 19 | Read screen → act | ✅ | 99% | exposed screenshot-wrong-workspace bug, fixed |
| 20 | Timed full workflow | ✅ | – | **39.0s** wall clock; ~1.5s desktop, rest is model turns |
| 21 | Command runner | ✅ | 78% | |
| 22 | Tic-tac-toe | ✅ | – | 6.3s, 4 moves, 0 LLM calls; first attempt read a cartoon |
| 23 | vibezAI music | ✅ | 44%→launched | search→play→volume 25%→wait→T→n; sink was muted |
| 24 | Slack dated attachment | ✅ | substring | already on 9/16; download had no dialog |
| 25 | Slack first link on date | ✅ | substring | Ctrl+K to DM; wheel scroll unreliable, Page_Up worked; opened pi.dev |

**24/25 pass, 1 partial.** kev resolved 10 natural-language targets, 9 correct;
the one miss was 57% (barely over gate) between two same-class windows.

Three bugs found and fixed by the run: tool-result image format, click
ignoring x_pct, screenshot not switching workspace. Two limits documented:
DnD needs a unified virtual pointer; identical titles need window_address.
