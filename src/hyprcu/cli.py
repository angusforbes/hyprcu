"""hyprcu CLI: the shell verbs (see verbs.py) plus `doctor` and `stop`.

Upstream's cli.py also carried `init` (MCP-client registration wizard),
`journal`/`replay` (audit log), and skill installation. hyprcu keeps the
verbs — every MCP tool callable from bash, a ~20 ms cold start for the
installed binary (a few hundred ms under `uv run`) — and the two commands
that stand alone.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys


def doctor() -> int:
    """Check the binaries and session the primitives depend on."""
    ok = True
    for b in ("hyprctl", "grim", "wtype"):
        found = shutil.which(b)
        print(f"{'ok ' if found else 'MISSING'}  {b:10s} {found or ''}")
        ok &= bool(found)
    for b in ("busctl", "wl-copy", "wl-paste", "magick"):
        found = shutil.which(b)
        print(f"{'ok ' if found else 'opt'}  {b:10s} {found or '(optional)'}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    print(f"{'ok ' if sig else 'MISSING'}  HYPRLAND_INSTANCE_SIGNATURE {sig or ''}")
    ok &= bool(sig)
    try:
        got = subprocess.run(
            ["hyprctl", "version"], capture_output=True, text=True, timeout=3
        ).stdout.splitlines()
        print(f"ok   {got[0] if got else ''}")
    except Exception as e:  # noqa: BLE001
        print(f"MISSING  hyprctl not answering: {e}")
        ok = False
    return 0 if ok else 1


def stop() -> int:
    """Kill any running hyprcu server or verb. No beacon in this fork, so
    this is a pgrep; bind it to a key as the panic switch."""
    me = os.getpid()
    out = subprocess.run(
        ["pgrep", "-f", "python.*-m hyprcu|hyprcu"], capture_output=True, text=True
    ).stdout.split()
    pids = [int(p) for p in out if int(p) != me]
    for p in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(p, signal.SIGTERM)
    print(f"stopped {len(pids)} process(es)" if pids else "nothing running")
    return 0


# ── surface verbs.py expects; the beacon/journal ones are no-ops here ──────
def lock() -> None: ...          # verbs use a file lock via cli_state; nothing extra
def _take_beacon() -> bool: return True
def init(*a, **k) -> int:
    print("hyprcu has no init wizard. Add to your MCP config:\n"
          '  {"command": "uv", "args": ["run", "--directory", "<repo>", "python", "-m", "hyprcu"]}')
    return 0
def journal_cmd(*a, **k) -> int:
    print("hyprcu has no journal (removed with the trust layer).")
    return 1
def replay(*a, **k) -> int:
    print("hyprcu has no replay (removed with the trust layer).")
    return 1


_USAGE = """\
usage: hyprcu [VERB ...]        hyprcu VERB --help for a verb's flags

no arguments   run the MCP stdio server (this is what MCP clients spawn)

server; for agents that run commands). Observation, works in read-only mode:
  desktop                        monitors, workspaces, windows, active, cursor, layers
  screenshot [--window ADDR] [--region x,y,WxH] [--scale F] [--stable] [--lossless]
             [--out PATH]
  zoom X Y [--size WxH] [--window ADDR] [--stable] [--lossless] [--out PATH]
  ui [--window ADDR] [--name TEXT] [--all]
  marks [--window ADDR] [--name TEXT] [--out PATH]
  binds
  wait_for EVENT [--match TEXT] [--timeout S]
Acting (refused with exit 3 under HYPRCU_READONLY; all take --dry-run, which
rehearses; all but launch and clipboard take --then none|desktop|ui|screenshot,
which appends the effect; pointer, keyboard and click_ui take --allow-auth):
  pointer move X Y | click [X Y] [--button B] [--double] | drag X Y TO_X TO_Y [--button B]
          | scroll DY [DX] [--at X Y]
  keyboard type TEXT|- [--window ADDR] | key COMBO [--window ADDR]
  click_ui NAME [--window ADDR] [--index I] [--button B] [--double]   or   click_ui --mark N
  hypr workspace WS | focus_window ADDR | move_window ADDR WS | close_window ADDR
       | fullscreen [ADDR] | toggle_floating [ADDR]
  launch [--workspace WS] [--wait S] COMMAND...   (the app's own flags after --)
  use_bind COMBO
  sequence STEPS|@file|- [--no-stop-on-change]
  clipboard read | write TEXT|-          needs HYPRCU_CLIPBOARD=1
Every tool verb takes --json (raw result, one line). click-ui, use-bind and
wait-for are accepted spellings. Exit: 0 ok, 1 error, 2 usage, 3 refused,
4 no result. hyprcu VERB [ACTION] --help shows the flags.

For the owner:
  doctor         diagnose dependencies, session, protocols; exit 0 if green
  stop           emergency stop: signal a running server to shut down safely
                 (bind it: bind = SUPER SHIFT, BackSpace, exec, hyprcu stop)
                 --acts, --refused, -n N
                 prints the plan and stops unless --execute is given
  serve          the MCP stdio server, explicitly
  --version
"""


def main(argv: list[str] | None = None) -> int:
    """No args → MCP server on stdio (so one binary is both the server and the
    CLI). --help/--version never start the server: an agent's shell has a piped
    stdin and a server started there waits forever for a client."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        from hyprcu.server import main as server_main
        server_main()
        return 0
    if argv[0] in ("-h", "--help"):
        print(_USAGE, end="")
        sys.exit(0)
    if argv[0] == "--version":
        from hyprcu import __version__
        print(f"hyprcu {__version__} (hypruse fork)")
        sys.exit(0)
    from hyprcu import verbs
    try:
        code = verbs.main(argv)
        if not sys.stdout.closed:
            sys.stdout.flush()
    except BrokenPipeError:   # `hyprcu desktop | head` closed early — the reader's choice
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)
