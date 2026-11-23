#!/bin/bash
# env.sh : sourced by the test scripts. A separate test environment, apart from the user's own game and desktop:
#  - display: a headless sway (own Wayland socket, no input devices, never on the user's screen), see display.sh
#  - caches: the GPU drivers' shader caches and XDG cache/config under $FP_ENV (the user's game shares
#    ~/.cache/nvidia otherwise), saves under /Games/TF-OOT/fptest-data
FP_ENV=${FP_ENV:-/Games/TF-OOT/fptest-env}
FP_GAME=${FP_GAME:-/Games/TF-OOT/FPTest}
export WAYLAND_DISPLAY=wayland-fptest
export SWAYSOCK=$XDG_RUNTIME_DIR/sway-fptest.sock
export GAME_OUT=${GAME_OUT:-$FP_ENV/game.out}
unset DISPLAY HYPRLAND_INSTANCE_SIGNATURE
game_env() {   # the environment the game runs with
  env XDG_DATA_HOME=/Games/TF-OOT/fptest-data XDG_CACHE_HOME=$FP_ENV/cache XDG_CONFIG_HOME=$FP_ENV/config \
      __GL_SHADER_DISK_CACHE_PATH=$FP_ENV/cache/nvidia MESA_SHADER_CACHE_DIR=$FP_ENV/cache/mesa \
      HOOKSHOT_NO_UPDATE_CHECK=1 SDL_GAMECONTROLLER_IGNORE_DEVICES=0x045e/0x028e SDL_VIDEODRIVER=wayland \
      WAYLAND_DISPLAY=$WAYLAND_DISPLAY "$@"
}
mkdir -p $FP_ENV/cache/nvidia $FP_ENV/cache/mesa $FP_ENV/config
