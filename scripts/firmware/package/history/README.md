# Historical tools (not used by the build)

These produced the published v1.3.0 images by exchanging only the player in an already built image
(first the V1 SSC player fix, then the final relabel). `build_all_upt.sh` builds the same result directly.

* `swap_player.sh BASE.upt PLAYER BOARD_MARKER LABEL OUT.upt` - replace `usr/bin/compas_player` in any
  Compás image and rechunk it. Works with stock host tools.
* `swap_v1_player.py` - the stricter V1 variant (preserves xattrs and ownership through a squashfs pseudo
  manifest). It needs a squashfs-tools 4.6.1 build whose `unsquashfs -pf` is patched to print xattrs
  NUL-terminated (stock 4.6.1 crashes on the V1 image), pointed to by `SQUASHFS_TOOLS`. That patched build
  is not in this repository. It imports `repack_v1_upt.py` from the parent folder.
