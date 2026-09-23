#!/usr/bin/env bash
# (Re)start the invisible nested Hyprland used for hyprcu testing.
#
# A second Hyprland runs as a window on host workspace 9 (silent, never focused);
# its own output is disabled and a headless output hosts its workspaces, so it
# renders and screenshots without appearing on screen, and its input never
# touches the host seat. Writes /tmp/hyprcu-nested/env.sh; use it with
#   . /tmp/hyprcu-nested/env.sh; hyprcu desktop
#
# Restart also clears a STUCK MODIFIER: the nested compositor gets the host
# keyboard, so pressing Super while its window has host focus can leave Super
# "held" inside it forever; every later key then carries Super (ctrl+t in
# Chromium does nothing, Return in foot prints ';9;13~').
#
# Usage: tools/nested-session.sh [--no-apps]
set -euo pipefail
D=/tmp/hyprcu-nested
mkdir -p "$D/site"
[ -f "$D/hyprland.lua" ] || cat >"$D/hyprland.lua" <<'EOF'
-- Minimal nested Hyprland for hyprcu testing (no Omarchy autostart/bar).
hl.monitor({ output = "", mode = "1600x1000", position = "auto", scale = 1 })
EOF

# stop the old instance (only nested ones: they run with our config file)
pkill -f "Hyprland -c $D/hyprland.lua" 2>/dev/null && sleep 1.5 || true

before=$(ls "$XDG_RUNTIME_DIR/hypr" 2>/dev/null | sort)
hyprctl dispatch "hl.dsp.exec_cmd(\"[workspace 9 silent] Hyprland -c $D/hyprland.lua\")" >/dev/null
sig=""
for _ in $(seq 50); do
  sleep 0.2
  sig=$(comm -13 <(echo "$before") <(ls "$XDG_RUNTIME_DIR/hypr" | sort) | head -1)
  [ -n "$sig" ] && [ -S "$XDG_RUNTIME_DIR/hypr/$sig/.socket.sock" ] && break
done
[ -n "$sig" ] || { echo "nested Hyprland did not start" >&2; exit 1; }
export HYPRLAND_INSTANCE_SIGNATURE=$sig
sleep 1
wl=$(hyprctl -j instances | python3 -c "import json,sys; print(next(i['wl_socket'] for i in json.load(sys.stdin) if i['instance']=='$sig'))")

hyprctl output create headless TEST >/dev/null
sleep 0.5
hyprctl eval 'hl.monitor({ output = "WAYLAND-1", disabled = true })' >/dev/null
hyprctl eval 'hl.monitor({ output = "TEST", mode = "1600x1000", position = "0x0", scale = 1 })' >/dev/null

cat >"$D/env.sh" <<EOF
export HYPRLAND_INSTANCE_SIGNATURE=$sig
export WAYLAND_DISPLAY=$wl
export HYPRCU_CHOOSER=\${HYPRCU_CHOOSER:-jev}
EOF

# test site
ss -ltn | grep -q '127.0.0.1:8765 ' ||
  (cd "$D/site" && setsid python3 -m http.server 8765 --bind 127.0.0.1 >"$D/http.log" 2>&1 &)

if [ "${1:-}" != "--no-apps" ]; then
  export WAYLAND_DISPLAY=$wl
  hyprctl dispatch 'hl.dsp.exec_cmd("[workspace 1 silent] foot")' >/dev/null
  hyprctl dispatch "hl.dsp.exec_cmd(\"[workspace 2] chromium --ozone-platform=wayland --force-renderer-accessibility --user-data-dir=$D/chromium-profile --no-first-run --no-default-browser-check http://localhost:8765/\")" >/dev/null
  sleep 3
fi
echo "nested: $sig on $wl  (. $D/env.sh)"
