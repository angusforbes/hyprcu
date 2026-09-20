#!/bin/bash
export HF_HUB_DISABLE_XET=1 KEV_DTYPE=bf16 KEV_QUANT=nf4
cd /home/agf/Work/kev
exec uv run --extra serve python -u -m kev.serve --run jaredpalmer/kev-4b --port 8009
