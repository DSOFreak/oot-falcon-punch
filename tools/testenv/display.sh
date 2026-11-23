#!/bin/bash
# display.sh [start|stop|status] : the headless sway the tests run in (1920x1080). Nothing shows on the real screen
# and it reads no input devices: keys come only from wtype on its socket (key.sh).
. "$(dirname "$0")/env.sh"
case ${1:-start} in
  status) [ -S $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY ] && swaymsg -t get_outputs -r | python3 -c "import json,sys;[print(o['name'],o['current_mode']) for o in json.load(sys.stdin)]" ;;
  stop) swaymsg exit >/dev/null 2>&1; sleep 1; rm -f $SWAYSOCK $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY ;;
  start)
    [ -S $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY ] && swaymsg -t get_version >/dev/null 2>&1 && exit 0
    cat > $FP_ENV/sway.conf <<CONF
output HEADLESS-1 mode 1920x1080 position 0 0
default_border none
focus_follows_mouse no
for_window [app_id=".*"] fullscreen enable
for_window [class=".*"] fullscreen enable
CONF
    rm -f $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY $SWAYSOCK   # (sway makes its IPC socket at $SWAYSOCK)
    before=$(cd $XDG_RUNTIME_DIR; ls -d wayland-[0-9]* 2>/dev/null | grep -v lock)
    # (sway names its socket wayland-N; the env var for the clients is fixed, so a symlink points at it)
    ( unset WAYLAND_DISPLAY; WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1 \
      setsid sway --unsupported-gpu -c $FP_ENV/sway.conf > $FP_ENV/sway.log 2>&1 & )
    for i in $(seq 1 50); do
      s=$(cd $XDG_RUNTIME_DIR; for f in wayland-[0-9]*; do case $f in *.lock) ;; *) echo "$before" | grep -qx "$f" || echo $f;; esac; done | head -1)
      [ -n "$s" ] && break; sleep 0.2
    done
    [ -z "$s" ] && { echo "sway did not start:"; tail -20 $FP_ENV/sway.log; exit 1; }
    ln -sf $XDG_RUNTIME_DIR/$s $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY
    for i in $(seq 1 25); do [ -S $SWAYSOCK ] && break; sleep 0.2; done
    swaymsg -t get_version >/dev/null && echo "headless sway up on $s (as $WAYLAND_DISPLAY)" ;;
esac
