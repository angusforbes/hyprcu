#!/bin/bash
# Tic-tac-toe helper — uses window-relative percentages, not absolute pixels.
# Usage: ttt.sh <command> [args]
#   setup          — find/launch Chromium, open tictactoe tab, return window info
#   click <r> <c>  — click cell (1-3, 1-3) using percentages
#   restart        — click Restart game
#   shot [name]    — screenshot the board area
#   score          — screenshot the score area

# Board geometry: the Google TTT grid is a FIXED ~210x210 logical px square,
# horizontally centered in the results column. The results column is
# left-aligned at ~x=8px in narrow windows, and ~x=150px in wide windows.
# Rather than percentages (which break on resize), we locate the grid center
# and use fixed cell spacing.
#
# Grid center X = center of the search results card
# Grid center Y = fixed offset from top (~62% of a 850px-tall window)
GRID_SIZE=210      # logical px, full 3x3 grid
CELL=70            # logical px per cell
GRID_CY_PCT=0.62   # grid center Y as fraction of window height
RESTART_DY=135     # Restart button is ~135px below grid center

grid_center() {
  # prints "cx cy" in logical coords
  read -r ADDR WX WY WW WH <<< "$(win_info)"
  if [ -z "$ADDR" ]; then echo "ERROR"; return 1; fi
  # Results card: in narrow window starts at x≈8, width≈650. In wide, x≈150, width≈650.
  # Card is always ~650px wide. Card center = WX + card_left + 325.
  # card_left ≈ 8 if WW < 900 else 150
  python3 -c "
ww=$WW; wx=$WX; wy=$WY; wh=$WH
card_left = 8 if ww < 900 else 150
cx = wx + card_left + 325
cy = wy + int(wh * $GRID_CY_PCT)
print(f'{cx} {cy}')"
}

win_info() {
  hyprctl clients -j | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    if c['class']=='chromium' and 'tictactoe' in c['title'].lower():
        print(f\"{c['address']} {c['at'][0]} {c['at'][1]} {c['size'][0]} {c['size'][1]}\")
        break"
}

cell_logical() {
  # args: row col (1-3) → prints "x y" in logical coords
  local r=$1 c=$2
  read -r cx cy <<< "$(grid_center)"
  python3 -c "
cx,cy=$cx,$cy; cell=$CELL
x = cx + ($c-2)*cell
y = cy + ($r-2)*cell
print(f'{x} {y}')"
}

focus_game() {
  read -r ADDR _ <<< "$(win_info)"
  if [ -z "$ADDR" ]; then echo "ERROR: no tictactoe window"; return 1; fi
  hyprctl dispatch "hl.dsp.focus({window = \"address:$ADDR\"})" >/dev/null
  sleep 0.15
}

case "$1" in
  setup)
    read -r ADDR WX WY WW WH <<< "$(win_info)"
    if [ -z "$ADDR" ]; then
      echo "No tictactoe tab. Opening one..."
      CHROME=$(hyprctl clients -j | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    if c['class']=='chromium':
        print(c['address']); break")
      if [ -z "$CHROME" ]; then
        hyprctl dispatch 'hl.dsp.exec_cmd({cmd = "chromium"})' >/dev/null
        sleep 3
        CHROME=$(hyprctl clients -j | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    if c['class']=='chromium':
        print(c['address']); break")
      fi
      hyprctl dispatch "hl.dsp.focus({window = \"address:$CHROME\"})" >/dev/null
      sleep 0.3
      wtype -M ctrl -k t -m ctrl; sleep 0.6
      wtype "tictactoe"; wtype -k Return; sleep 2.5
      read -r ADDR WX WY WW WH <<< "$(win_info)"
    fi
    echo "window=$ADDR at=($WX,$WY) size=${WW}x${WH}"
    ;;
  click)
    focus_game || exit 1
    read -r x y <<< "$(cell_logical $2 $3)"
    hyprctl dispatch "hl.dsp.cursor.move({ x = $x, y = $y })" >/dev/null
    sleep 0.03; wlrctl pointer click
    echo "clicked [$2,$3] → ($x,$y)"
    ;;
  restart)
    focus_game || exit 1
    read -r cx cy <<< "$(grid_center)"
    y=$((cy + RESTART_DY))
    hyprctl dispatch "hl.dsp.cursor.move({ x = $cx, y = $y })" >/dev/null
    sleep 0.03; wlrctl pointer click
    echo "restart clicked at ($cx,$y)"
    ;;
  shot)
    focus_game || exit 1
    read -r cx cy <<< "$(grid_center)"
    half=$((GRID_SIZE/2 + 40))
    x0=$((cx-half)); y0=$((cy-half-20)); w=$((half*2)); h=$((half*2+40))
    grim -s 1 -g "$x0,$y0 ${w}x${h}" -t jpeg -q 85 "/tmp/ttt-${2:-board}.jpg"
    echo "/tmp/ttt-${2:-board}.jpg"
    ;;
  center)
    grid_center
    ;;
  *)
    echo "usage: ttt.sh setup|click r c|restart|shot [name]|score"
    ;;
esac
