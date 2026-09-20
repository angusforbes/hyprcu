#!/bin/bash
# Manual kev launcher. The canonical way to run kev is the systemd user
# unit `kev.service` (start/stop/restart/status via `systemctl --user`),
# which runs on CUDA in NF4, offline-safe, and auto-starts at login.
# This script is the manual fallback and mirrors the unit's env.
export HF_HUB_DISABLE_XET=1 HF_HUB_OFFLINE=1 KEV_DTYPE=bf16 KEV_QUANT=nf4
cd /home/agf/Work/kev
exec uv run --extra serve python -u -m kev.serve --run jaredpalmer/kev-4b --port 8009
