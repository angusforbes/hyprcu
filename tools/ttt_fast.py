#!/usr/bin/env python3
"""
Fast tic-tac-toe: pixel-sample board reader + OpenDecision move picker.

No screenshots sent to a large model. Per-turn loop:
  grim (65ms) → pixel sample (5ms) → OpenDecision choice (~200ms) → click (50ms)

Usage: ttt_fast.py [--no-model]   (--no-model uses minimax instead of OpenDecision)
"""
import subprocess, sys, time, json, os
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Work/OpenDecision/src"))

TTT = Path(__file__).parent / "ttt.sh"
CELL = 70
USE_MODEL = "--no-model" not in sys.argv

def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()

def grid_center():
    cx, cy = sh(str(TTT), "center").split()
    return int(cx), int(cy)

def cell_xy(r, c, cx, cy):
    return cx + (c - 2) * CELL, cy + (r - 2) * CELL

def read_board(cx, cy):
    """Sample the pixel at each cell center. Returns 9-char string, row-major."""
    from PIL import Image
    half = 120
    x0, y0 = cx - half, cy - half
    sh("grim", "-s", "1", "-g", f"{x0},{y0} {half*2}x{half*2}", "-t", "png", "/tmp/ttt-board.png")
    img = Image.open("/tmp/ttt-board.png").convert("RGB")
    board = []
    for r in (1, 2, 3):
        for c in (1, 2, 3):
            px, py = cell_xy(r, c, cx, cy)
            ix, iy = px - x0, py - y0
            # O is a RING (~20px radius, hollow center) so sample a ring of points
            # at radius 18 plus the center. X's arms cross the center and diagonals.
            pts = [(0, 0)]
            for ang in range(0, 360, 30):
                import math
                pts.append((int(18 * math.cos(math.radians(ang))), int(18 * math.sin(math.radians(ang)))))
            for d in (-10, 10):
                pts += [(d, d), (d, -d)]
            vals = [img.getpixel((ix + dx, iy + dy)) for dx, dy in pts]
            # X is dark grey (~80,80,80); O is cream (~240,235,215); empty is teal (~20,190,175)
            dark = sum(1 for (R, G, B) in vals if R < 120 and G < 120 and B < 120)
            cream = sum(1 for (R, G, B) in vals if R > 200 and G > 200 and B > 180)
            if cream >= 3: board.append("O")
            elif dark >= 2: board.append("X")
            else: board.append(".")
    return "".join(board)

def winner(b):
    lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a, b2, c in lines:
        if b[a] != "." and b[a] == b[b2] == b[c]:
            return b[a]
    return "D" if "." not in b else None

def minimax(b, player):
    w = winner(b)
    if w == "X": return 1, None
    if w == "O": return -1, None
    if w == "D": return 0, None
    best = (-2, None) if player == "X" else (2, None)
    for i in range(9):
        if b[i] == ".":
            nb = b[:i] + player + b[i+1:]
            score, _ = minimax(nb, "O" if player == "X" else "X")
            if player == "X" and score > best[0]: best = (score, i)
            if player == "O" and score < best[0]: best = (score, i)
    return best

_engine = None
def pick_move_model(board):
    """Ask OpenDecision which empty cell to play."""
    global _engine
    if _engine is None:
        from opendecision.engine import OpenDecisionEngine
        _engine = OpenDecisionEngine()
    empties = [i for i in range(9) if board[i] == "."]
    if len(empties) == 1:
        return empties[0], 1.0, 0
    rows = [board[0:3], board[3:6], board[6:9]]
    state = (f"Tic-tac-toe. I am X, opponent is O. Board rows top to bottom: "
             f"{rows[0]} / {rows[1]} / {rows[2]}. Dots are empty. "
             f"Cells are numbered 1-9 left-to-right, top-to-bottom.")
    criteria = {}
    for i in empties:
        r, c = divmod(i, 3)
        # give the model tactical hints per cell so a text NLI model can reason
        nb = board[:i] + "X" + board[i+1:]
        wins = winner(nb) == "X"
        ob = board[:i] + "O" + board[i+1:]
        blocks = winner(ob) == "O"
        tag = " (WINS immediately)" if wins else " (BLOCKS opponent win)" if blocks else ""
        criteria[f"cell{i+1}"] = f"Play cell {i+1} (row {r+1}, column {c+1}){tag}"
    t0 = time.time()
    res = _engine.choice(state=state, instructions="Which cell should X play to win or avoid losing?", criteria=criteria)
    ms = int((time.time() - t0) * 1000)
    choice = res["choice"]
    idx = int(choice.replace("cell", "")) - 1
    return idx, res["probabilities"][choice], ms

def click_cell(idx):
    r, c = divmod(idx, 3)
    sh(str(TTT), "click", str(r + 1), str(c + 1))

def main():
    print(sh(str(TTT), "setup"))
    sh(str(TTT), "restart"); time.sleep(0.9)
    cx, cy = grid_center()
    print(f"grid center: ({cx},{cy})  mode: {'OpenDecision' if USE_MODEL else 'minimax'}")

    if USE_MODEL:
        t0 = time.time(); pick_move_model("........."[:8] + ".")  # warm up
        print(f"model warmup: {int((time.time()-t0)*1000)}ms\n")

    game_start = time.time()
    turn = 0
    prev_board = None
    stale = 0
    while turn < 6:
        turn += 1
        t_turn = time.time()
        t0 = time.time(); board = read_board(cx, cy); t_read = int((time.time() - t0) * 1000)
        w = winner(board)
        if w:
            break
        if board == prev_board:
            stale += 1
            if stale >= 2:
                sh("grim", "-s", "1", "-g", f"{cx-160},{cy-200} 320x400", "-t", "jpeg", "-q", "85", "/tmp/ttt-stuck.jpg")
                print(f"STUCK: board unchanged after click ({board}). Screenshot: /tmp/ttt-stuck.jpg")
                return None, "stuck", 0
        else:
            stale = 0
        prev_board = board
        if USE_MODEL:
            idx, prob, t_model = pick_move_model(board)
        else:
            t0 = time.time(); _, idx = minimax(board, "X"); t_model = int((time.time() - t0) * 1000); prob = 1.0
        t0 = time.time(); click_cell(idx); t_click = int((time.time() - t0) * 1000)
        r, c = divmod(idx, 3)
        print(f"turn {turn}: {board[0:3]}/{board[3:6]}/{board[6:9]} → X@[{r+1},{c+1}] p={prob:.2f} "
              f"| read {t_read}ms  decide {t_model}ms  click {t_click}ms  = {int((time.time()-t_turn)*1000)}ms")
        time.sleep(0.9)  # O's animation

    total = int((time.time() - game_start) * 1000)
    rows = [board[0:3], board[3:6], board[6:9]]
    art = "\n-----------\n".join(" | ".join(row) for row in rows)
    result = {"X": "X wins", "O": "O wins", "D": "Draw"}[w]
    print(f"\n{art}\n\n{result} in {total}ms ({turn-1} moves)")
    return art, result, total

if __name__ == "__main__":
    main()
