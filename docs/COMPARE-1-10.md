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
