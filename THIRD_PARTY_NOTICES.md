# Third-party notices

Licence texts and provenance sit beside the files they cover. Summary:

| Material | Location | Licence / notice |
| --- | --- | --- |
| Montserrat, Noto Sans, Noto Sans Arabic | `assets/fonts` | SIL OFL 1.1 (`*-OFL.txt`) |
| Noto Sans CJK derived fonts, `default.otf` | `assets/fonts` | Apache-2.0 (see `NOTICE.md`; licence text is not in the tree: add `https://www.apache.org/licenses/LICENSE-2.0.txt` before publishing) |
| `Thai.ttf` / `thai.ttf` (CS ChatThaiUI) | `assets/fonts` | CC BY 4.0 (`NOTICE.md`); copied from HiBy stock firmware |
| Font Awesome, UNSCII | `assets/fonts` | `FONTAWESOME_LICENSE.txt`, `UNSCII_LICENSE.txt` |
| Breeze icons | `assets/theme2/*/BREEZE_*`, `assets/bootloader/selector/icons` | LGPL-3.0 (`COPYING-ICONS`, `LGPL-3.0.txt`) |
| Other icons | `assets/theme*/**/SOURCES.txt`, `LICENSE*` | per folder |
| Stock HiBy / TempoTec artwork and fonts | `assets/theme1`, `assets/theme2` (parts), `assets/*/theme2/usb`, `default.otf`, `Thai.ttf` | derived from vendor firmware, see "Concerns" |
| SpeexDSP, alsa-plugins speexrate | `firmware/overlay/usr/lib`, `usr/share/licenses/speex-runtime` | BSD / LGPL, texts included |
| dosfstools, exfatprogs, ntfs-3g (`fsck.*`, `ntfsfix`) | `firmware/overlay/usr/sbin`, `usr/share/licenses/sd-fsck` | GPL-2.0 / LGPL, texts included; build recipe `scripts/build/storage/build_sd_fsck_tools.sh` |
| `gt9xx_touch.ko` open module | `firmware/kernel/open-modules` | GPL-2.0 (kernel module); sources/patches under `firmware/kernel/module-patches` |
| Linux kernel and driver patches | `firmware/kernel` | GPL-2.0 |
| BlueALSA, BlueZ, D-Bus, GLib, ALSA, LDAC, fdk-aac, libopenaptx patches | `scripts/base_image/patches` | patches to upstream sources (MIT, GPL/LGPL, Apache-2.0 variants); sources are fetched at pinned commits |
| Rockbox bootloader patch | in compas-player (`firmware/bootloader`) | GPL-2.0 |
| libssc | `third_party/libssc` | **no licence stated**, see "Concerns" |

## Concerns before making the repository public

1. `third_party/libssc` is a C translation recovered from a Samsung ARM encoder image (coefficient tables in
   `ssc_image_data.h`). It has no licence file and may be derived from proprietary code; the same applies to
   the `bluealsad` binary that links it statically.
2. Stock-derived files: HiBy / TempoTec fonts, icons, kernel modules and scripts are redistributed from
   vendor firmware (and the weekly images contain the vendor kernel). Confirm that redistribution is acceptable.
3. `firmware/vendor_drivers.json` holds a Dropbox share link with an `rlkey` query parameter; drop the key or the link.
4. The Apache-2.0 licence text for the Noto-derived fonts should be added.
