# hyprcu tools

| file | what |
|---|---|
| `kev-serve.sh` | start kev-4b (NF4, 3.6 GB VRAM) as the `/v1/systemone` server hyprcu's `pick.py` calls |
| `kev_bench.py` | 9 window-selection queries with ground truth; `--url` to point at Jev/openjev for A/B |
| `window_pick.py` | earlier OpenDecision-based picker, kept as the harness that produced Lesson 18 |
| `ttt.sh`, `ttt_fast.py` | Google tic-tac-toe: anchored-offset grid, pixel-sample board reader, minimax. 5–6 s/game, 0 LLM calls |

kev itself lives in `~/Work/kev` (jaredpalmer/kev, patched for `KEV_QUANT=nf4`).
