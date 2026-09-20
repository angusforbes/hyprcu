# hyprcu tools

| file | what |
|---|---|
| `kev.service` | **canonical launcher** — a systemd *user* unit (`systemctl --user start/stop/status kev`). Runs kev-4b on CUDA in NF4, offline-safe (`HF_HUB_OFFLINE=1`; weights cached), auto-starts at login. Unit at `~/.config/systemd/user/kev.service` |
| `kev-serve.sh` | manual kev launcher (fallback), mirrors the unit's env |
| `kev_bench.py` | 9 window-selection queries with ground truth; `--url` to point at Jev/openjev for A/B |
| `window_pick.py` | earlier OpenDecision-based picker, kept as the harness that produced Lesson 18 |
| `ttt.sh`, `ttt_fast.py` | Google tic-tac-toe: anchored-offset grid, pixel-sample board reader, minimax. 5–6 s/game, 0 LLM calls |

kev itself lives in `~/Work/kev` (jaredpalmer/kev, patched for `KEV_QUANT=nf4`).
