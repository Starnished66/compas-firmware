# Disabled tests

These pass only on the original author's machine and are kept for reference, not run by CI:

* `*radio_pinning`, `*experimental_radio`, `*combined_upt`, `*radio_upt` read fixture trees that were never committed
  (`compas-ui-stall-fixes-20261008/...`, `compas-driver-candidates-20261009/...`).
* `*radio_suspend_integration` reads player sources (`src/hardware/power/power_suspend.c`); it needs to live in compas-player.
* `*run_early_splash_spec.sh` builds against the player's `src/bootloader/display/fb_draw.h` through a relative include that no longer resolves.

Fix the fixture paths (or move the player-source tests to compas-player) before re-enabling.
