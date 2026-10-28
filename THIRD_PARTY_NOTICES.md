# Third-party notices

Licence texts and provenance sit beside the files they cover. Summary:

| Material | Location | Licence / notice |
| --- | --- | --- |
| Montserrat, Noto Sans, Noto Sans Arabic | `assets/fonts` | SIL OFL 1.1 (`*-OFL.txt`) |
| Noto Sans CJK derived fonts, `default.otf` | `assets/fonts` | Apache-2.0 (`licenses/Apache-2.0.txt`, `assets/fonts/NOTICE.md`) |
| `Thai.ttf` / `thai.ttf` (CS ChatThaiUI) | `assets/fonts` | CC BY 4.0 (`NOTICE.md`); copied from HiBy stock firmware |
| Font Awesome, UNSCII | `assets/fonts` | `FONTAWESOME_LICENSE.txt`, `UNSCII_LICENSE.txt` |
| Breeze icons | `assets/theme2/*/BREEZE_*`, `assets/bootloader/selector/icons` | LGPL-3.0 (`COPYING-ICONS`, `LGPL-3.0.txt`) |
| Other icons | `assets/theme*/**/SOURCES.txt`, `LICENSE*` | per folder |
| Stock HiBy / TempoTec artwork and fonts | `assets/theme1`, `assets/theme2` (parts), `assets/*/theme2/usb`, `default.otf`, `Thai.ttf` | derived from vendor firmware, see "Concerns" |
| SpeexDSP, alsa-plugins speexrate | `firmware/overlay/usr/lib`, `usr/share/licenses/speex-runtime` | BSD / LGPL, texts included |
| dosfstools, exfatprogs, ntfs-3g (`fsck.*`, `ntfsfix`) | `firmware/overlay/usr/sbin`, `usr/share/licenses/sd-fsck` | GPL-2.0 / LGPL, texts included; build recipe `scripts/build/storage/build_sd_fsck_tools.sh` |
| BlueZ 5.87 `bluetoothd`, `obexd` | `firmware/overlay/usr/share/licenses/bluez`, `scripts/base_image/patches/bluez` | GPL-2.0-or-later / LGPL-2.1-or-later, texts included; pinned tarball plus repository patches, `scripts/build/base/bluetooth/build_base_bluez.sh` |
| `gt9xx_touch.ko` open module | `firmware/kernel/open-modules` | GPL-2.0 (kernel module); sources/patches under `firmware/kernel/module-patches` |
| Linux kernel and driver patches | `firmware/kernel` | GPL-2.0 |
| BlueALSA, BlueZ, D-Bus, GLib, ALSA, LDAC, fdk-aac, libopenaptx patches | `scripts/base_image/patches` | patches to upstream sources (MIT, GPL/LGPL, Apache-2.0 variants); sources are fetched at pinned commits |
| Rockbox bootloader patch | in compas-player (`firmware/bootloader`) | GPL-2.0 |
| Phosphor icons, Material Symbols | `assets/theme2/launcher`, `wireless` | Phosphor: MIT, Copyright (c) 2023 Phosphor Icons (`licenses/Phosphor-MIT.txt`); Material Symbols: Apache-2.0, Copyright Google LLC (`licenses/Apache-2.0.txt`) |
| libssc | `third_party/libssc` | GPL-3.0 (`LICENSE`), the project's own reverse-engineered implementation (`PROVENANCE.md`); no Samsung code licence |

## Remaining notes

1. libssc and the `bluealsad` built from it implement a Samsung codec for interoperability; Samsung has not licensed them (see `third_party/libssc/PROVENANCE.md`).
2. Stock-derived files: HiBy / TempoTec fonts, icons (`hibylink`, AirPlay mark: vendor/third-party marks, licence unknown), kernel modules and scripts are redistributed from vendor firmware, and the images contain the vendor kernels.
3. `firmware/vendor_drivers.json` holds HiBy's public Dropbox beta link (with its `rlkey`); it is used only by the manual `--vendor-drivers` path.
4. Prebuilt binaries in `firmware/overlay` (SpeexDSP, fsck tools) embed build-host paths from their original build.
5. Some theme artwork has no recorded provenance; `assets/theme2/*/SOURCES.txt` say so where known.
