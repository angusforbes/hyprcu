# Tests 1–10 under four setups (2026-09-24)

Same driver (the Pi agent, Claude Opus), same tasks, same environment; only
the **text decider** and the **screen reader** change.

| Setup | Text decider (descriptions → window/control) | Screen reader (what happened / what is shown) |
|---|---|---|
| **S1 Original** | kev (kev-4b, local :8009) | the driver reads full screenshots |
| **S2 Jev** | Jev (TypeSafe cloud) | the driver reads `--then changes` crops (full screenshot only when needed) |
| **S3 Local** | kev-vision (Qwen3-VL-4B text readout, local :8010) | `check` with kev-vision only; the driver never sees an image |
| **S4 Hybrid** | Jev | `check` with kev-vision; answers below p=0.9 re-asked to Claude Haiku 4.5; the driver never sees an image |

## Environment: the nested session (invisible to the host screen)

| ws | window | description the driver must use |
|---|---|---|
| 1 | foot | "the terminal" |
| 2 | Chromium, Test Home (counter reset to 3) | "the web browser" |
| 3 | Strata (own D-Bus session, so **no accessibility tree**) | "the file browser" |
| 4 | Chromium, Team Chat page (channel sidebar) | "the chat window" |
| 5 | Obsidian | "the notes app" |

Deviations from docs/TESTS.md: Slack → a local chat page (Slack is single
instance and would open on the host); Strata runs in its own D-Bus session
(same reason), which removes its accessibility tree in every setup alike.

## The tasks (adapted from docs/TESTS.md)

1. List every open window with workspace, class and title.
2. Describe what the active window (the web browser) shows.
3. Focus "the notes app" and confirm it is active.
4. In "the terminal", run `echo "desktop control works"` and confirm the output.
5. In "the file browser", click Home in the sidebar and confirm it is showing the home folder.
6. In "the file browser", click Documents in the sidebar and report the files listed.
7. Go to "the chat window" and report the channels in its sidebar.
8. In "the file browser", right-click a file, report the context-menu items, press Escape, confirm it closed.
9. In "the web browser", open localhost:8765/long.html, scroll down 10 steps, report which section is at the top.
10. In "the web browser", open a new tab, go to localhost:8765/about.html, confirm it loaded.

## Rules

- Windows are always named by description (so the text decider is exercised).
- Every setup may use the text tools: `desktop`, `ui` (accessibility), actions, `wait_for`.
- S1/S2 may read images; **S3/S4 may not**: only `check` (choice / `--read` / `--locate`).
- No coordinates from memory: every click position must come from a tool result in that trial.
- Timing and turns run from the trial's first tool call to the driver's answer.
- Ground truth is checked independently after each trial and does not count.

## Results (one run per setup; order S3, S4, S2, S1)

Seconds / driver turns / images the driver read. Time is from a trial's first
command to the driver's next command after answering.

| Test | S1 Original (kev + screenshots) | S2 Jev + change crops | S3 Local (kev-vision) | S4 Hybrid (Jev + kev-vision → Haiku) |
|---|---|---|---|---|
| 1 list windows | 4 / 1 / 0 ✅ | 7 / 1 / 0 ✅ | 8 / 1 / 0 ✅ | 4 / 1 / 0 ✅ |
| 2 describe active window | 10 / 2 / 1 ✅ | (452*) / 1 / 0 ✅ | 5 / 1 / 0 ✅ | 4 / 1 / 0 ✅ |
| 3 focus "the notes app" | 7 / 1 / 0 ✅ kev 81% | 8 / 1 / 0 ✅ Jev 81% | 6 / 1 / 0 ✅ 100% | 5 / 1 / 0 ✅ Jev 82% |
| 4 echo in "the terminal" | 9 / 2 / 1 ✅ | 15 / 2 / 1 ✅ | 11 / 1 / 0 ✅ (after a tool fix†) | 9 / 1 / 0 ✅ |
| 5 file browser → Home | 26 / 4 / 2 ✅ | 25 / 3 / 1 ✅ | 17 / 2 / 0 ✅ | 21 / 2 / 0 ✅ |
| 6 Documents, list files | 22 / 4 / 2 ✅ exact | 18 / 2 / 1 ✅ exact‡ | 21 / 2 / 0 ⚠️ 9/9 items, 3 misspelled | 19 / 2 / 0 ⚠️ 9/9 items, 3 misspelled |
| 7 chat channels | 12 / 2 / 1 ✅ | 6 / 1 / 0 ✅ | 6 / 1 / 0 ✅ | 5 / 1 / 0 ✅ |
| 8 context menu, Escape | 33 / 6 / 3 ✅ | 32 / 5 / 2 ✅ | 24 / 3 / 0 ✅ 16/16 items | 27 / 3 / 0 ✅ |
| 9 scroll 10, top section | 14 / 2 / 1 ✅ | 13 / 2 / 1 ✅ | 17 / 2 / 0 ✅ | 19 / 2 / 0 ❌ scrolled 20§ |
| 10 new tab, about page | 25 / 2 / 1 ✅ | 8 / 1 / 0 ✅ | 10 / 1 / 0 ✅ | 10 / 1 / 0 ✅ |
| **total** | **162 s, 26 turns, 12 images; 10/10** | **~137 s¶, 19 turns, 6 images; 10/10** | **125 s, 15 turns, 0 images; 9/10 + 1 partial** | **124 s, 15 turns, 0 images; 8/10 + 1 partial** |

\* A ~7-minute stall before the driver's next turn (the command took <1 s); excluded.
¶ With T2 counted as ~5 s like the other setups.
† S3's first T4 attempt exposed `check --last` not working across CLI calls; fixed, trial rerun from reset.
‡ S2 reused the Documents position from T5's screenshot (a rule slip that saved a step).
§ Driver error, not the setup: the accessibility positions read right after the scroll were stale, so the driver scrolled again.

**Text decisions** (all correct): kev ~180 ms, kev-vision ~180 ms, Jev ~260–350 ms. "The web browser" was
ambiguous (two Chromium windows): kev (70–82%) and kev-vision (100%) chose the chat window, Jev the test
home (65–74%): Jev's confidence reflected the ambiguity; kev-vision's did not.

**Screen checks** (S3/S4): choice 0.4–1.8 s, `--read` 1.8–5 s, `--locate` ~4 s (the model writes coordinates).
Every choice check had p ≥ 0.98, so **S4 never escalated to Haiku**: on these tasks S4 = S3 with Jev.
kev-vision's weakness showed in open reading (S3/S4 T6: "reprieve" read as "reprise"/"repiieve",
"SmaleDynamics" as "SmaLeDynamics"); `--read` has no confidence, so it cannot escalate.

**What left the machine** (the driver is itself a cloud model, so its text always does): S1 12 images;
S2 6 images + window names to TypeSafe; S3 no images; S4 no images + window names to TypeSafe.

**Caveats.** One run each; the driver judged its own outputs (ground truth checked separately);
order effects (S3 ran first, S1 last, so S1 had the most layout practice and was still slowest);
T5 cannot fail (the reset leaves Strata on Home); T2 and T7 were answered from the accessibility
tree in S2–S4, so the reader did not matter there.

**Bugs found by running this:** `--dry-run` acted for real (fork stubs; fixed), `check --last`
across CLI calls (fixed), the reset script (fine: Hyprland reuses window addresses).
