# hyprcu docs

- **[LESSONS.md](LESSONS.md)** — everything learned driving this desktop:
  Hyprland 0.56 Lua dispatch, wtype/wlrctl quirks, model evaluations
  (OpenDecision, Needle, kev, Jev), and **app profiles** — `grep "app profile"`
  for Strata, Chromium, Slack, vibezAI, the Omarchy bar. Read the matching
  profile before touching an app.
- **[TESTS.md](TESTS.md)** — 25 desktop-interaction tests of increasing
  difficulty with results from three runs (bash prototype, pi extension,
  hyprcu). T1–T10 in 4.7s; T11–T20 in ~37s of which 25s is page loads.

Only §8 (bar workspace numbers), §14 (`omarchy toggle screensaver`) and §23
(bar audio widget) are Omarchy-specific. Everything else applies to any
Hyprland desktop.
