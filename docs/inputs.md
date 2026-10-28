# Build inputs

Nothing below is committed: stock firmware and prebuilt binaries are fetched and checked against a
SHA-256 that is tracked in this repository (no secrets are involved).

| Input | Used for | Source | Pin |
| --- | --- | --- | --- |
| `r1.upt`, `r3proii.upt`, `r3ii_2025.upt` | prepared base images (kernel, drivers, base system) | public `compas-player` release `staging-image-base` | `firmware/inputs.sha256` (equal to the release asset digests) |
| `bluealsad` | Samsung SSC Bluetooth (BlueALSA 5.0.0 + `bluealsa-ssc.patch`, libssc linked statically) | release `build-inputs` of this repository, asset `bluealsad` | `firmware/ssc-overlay.sha256` |
| `bluetoothd`, `obexd` | BlueZ 5.87 daemon with the repository patches (AVDTP endpoint rediscovery, AVRCP cover art) and the cover-art-only OBEX daemon | release `build-inputs` of this repository, assets `bluetoothd` and `obexd` | `firmware/ssc-overlay.sha256` |
| `v1-stock.upt` | official TempoTec V1 1.2 firmware (kernel, recovery, stock rootfs) | release `build-inputs` of this repository, asset `v1-stock.upt` (a byte-identical mirror of the vendor download) | `firmware/inputs.sha256` (`9f929a92...`) |
| `compas-player` `main` | all four players, loaders | public repository | - |

`scripts/build/firmware/fetch_inputs.sh DEST` downloads and verifies all of them.

Exact assets of release `build-inputs` (tag `build-inputs`):

| Asset name | SHA-256 | Size |
| --- | --- | --- |
| `bluealsad` | `d683e3389fbfb3e35351d3b44f9dafbbc4007136c1f2ee510702280415cc11c4` | 1 file, mode 0755 as installed |
| `bluetoothd` | `eb5de0da28f1b370768231259c917b9db60364f8a0b306fb0c8b919256a197aa` | stripped MIPS ELF, mode 0755 as installed |
| `obexd` | `45b34a14f92290c513f9e6804cc38eb9c355fd00e0c30e25912e25fddfaa0b7f` | stripped MIPS ELF, mode 0755 as installed |
| `v1-stock.upt` | `9f929a92319a05a81bbd16cbf0fb8a886a9bb2def192f5a6786b6ea7032fa05d` | 39,907,328 bytes |

The staging bases predate SSC and AVRCP cover art; the three daemons are applied at repack time through
`R1_RUNTIME_OVERLAY` / `R3_RUNTIME_OVERLAY` (a directory holding `usr/bin/bluealsad`,
`usr/libexec/bluetooth/bluetoothd` and `usr/libexec/bluetooth/obexd`; `build_all_upt.sh` passes `SSC_OVERLAY_DIR`).
`firmware/ssc-overlay.sha256` pins the three files by their path inside that directory.
The cover-art responder's init script (`S81compas_obex`) and D-Bus policy are tracked in `firmware/overlay`.
The bases already carry BlueZ 5.87 (`bluetoothd` and `obexd` of the same family and the same GLib 2.84 / D-Bus 1.16
libraries), so the overlay replaces whole daemons without touching any library.

TempoTec V1 is moved onto the same BlueZ set by `repack_v1_upt.py` (`install_bluez_stack`): the two overlay daemons,
the R1 base's `bluetoothctl`, `btmon`, `hciconfig`, `hcitool`, `libbluetooth.so.3.19.16` (the old 3.19.2 file stays, the
SONAME link moves) and `main.conf`, plus the tracked cover-art files from `firmware/overlay`. TempoTec's `bt_init`
(radio power-up and address) is kept, and so are V1's D-Bus 1.12 library and daemon: the 5.87 daemons resolve every symbol
against them (`LD_BIND_NOW=1` under qemu, see below), and V1's own BlueALSA 5 already runs on that library. `main.conf` is
the R1 one (pinned) with only V1's own `DiscoverableTimeout = 0` (stay discoverable until the player turns it off)
changed; `AutoEnable=false` is kept (the player decides when the controller is powered, as on the other boards).
`BroadcomHighPriority = true` is set on every board by `clean_os.py` (idempotent, after `Name`). It is the port of the
vendor patch of TempoTec's BlueZ 5.54: when a device's A2DP sink service connects, a Broadcom or Cypress controller
gets the vendor command 0xfd1a (connection handle, 0x01, 0x00) on a raw HCI socket, which raises the ACL link priority
so A2DP survives Wi-Fi traffic on the shared radio. The daemon option defaults to false and the controller check makes
it a no-op elsewhere. Live check on an R1: `hcitool -i hci0 cmd 0x3f 0x011a 0x0b 0x00 0x01 0x00` returns Command
Complete with status 00.
V1 takes its BlueALSA/GLib runtime, themes and fonts from the freshly built `r1.upt`.
The V1 stock image's origin is the TempoTec firmware download page (public Google Drive folder, file id
`1z8es1IXVFt2PhWLzUFVbv_D0rfGzjjes`, vendor MD5 `d3301d3930309b5433331a2aed741652`).

## Rebuilding bluealsad

Needs the Ingenic glibc 2.22 toolchain (see `scripts/base_image/README.md`). Run the build order there with
`SSC_STATIC=ON` for `build_base_bt_codecs.sh`, then `build_base_bluealsa.sh`; the resulting
`stage/usr/bin/bluealsad` is the overlay. The published v1.3.0 daemon was built from BlueALSA
`1935d6dcb8975f2d7a51aaafe61538d157224623` with `scripts/base_image/patches/bluealsa/bluealsa-ssc.patch`.
A rebuild is not guaranteed to be byte-identical; if you replace the daemon, update `firmware/ssc-overlay.sha256`
(the only place the hash lives) and re-upload the `build-inputs` asset.

## Rebuilding bluetoothd and obexd

`build_base_bluez.sh` applies every `scripts/base_image/patches/bluez/bluez-*.patch` to the pinned BlueZ 5.87
tarball (SHA-256 checked) and cross-builds with the Ingenic toolchain. It needs these inputs, all produced from
this repository or downloaded and hash-checked; nothing comes from a personal folder:

| Input | Where it comes from |
| --- | --- |
| Ingenic glibc 2.22 toolchain | `git clone https://github.com/tobunto/ingenic-toolchain-v5.2 scratch/ingenic-toolchain-v5.2`, checkout `4de21963b0f10c19118045f78c3e853a5e2c0be6` |
| stock root (`BASE_STOCK_ROOT`): vendor `libreadline`/`libncurses`/`libz`/`libexpat` and the glibc 2.22 loader | unpack the rootfs of `v1-stock.upt` (fetched and verified by `fetch_inputs.sh`) |
| D-Bus source | `git clone https://gitlab.freedesktop.org/dbus/dbus scratch/dbus`, checkout `958bf9db2100553bcd2fe2a854e1ebb42e886054` |
| zlib 1.3.2, Expat 2.8.4, GLib 2.84.4 (+ libffi, PCRE2), D-Bus 1.16.2 stages | `build_base_zlib.sh`, `build_base_expat.sh`, `build_base_glib.sh`, `build_base_dbus.sh` (they download pinned archives and write `scratch/base-upgrade/*/{current,stage}`, the defaults the BlueZ recipe reads) |
| GNU Readline 8.0 headers | downloaded and hash-checked by the BlueZ recipe |

Host tools: gcc, make, autoconf, automake, libtool, pkg-config, meson, ninja, cmake, curl, ripgrep (`rg`), `qemu-mipsel`,
`7z`, `unsquashfs`.

```sh
scripts/build/firmware/fetch_inputs.sh inputs          # also yields inputs/base/v1-stock.upt
7z x -y -oscratch/v1 inputs/base/v1-stock.upt
cat scratch/v1/ota_v0/rootfs.squashfs.[0-9]* > scratch/v1.squashfs
unsquashfs -no-xattrs -d scratch/stock-root scratch/v1.squashfs
export BASE_STOCK_ROOT=$PWD/scratch/stock-root BASE_DBUS_SOURCE=$PWD/scratch/dbus
bash scripts/build/base/system_libraries/build_base_zlib.sh
bash scripts/build/base/system_libraries/build_base_expat.sh
bash scripts/build/base/system_libraries/build_base_glib.sh
bash scripts/build/base/system_libraries/build_base_dbus.sh
bash scripts/build/base/bluetooth/build_base_bluez.sh
```

The overlay files are the stripped binaries of `scratch/base-upgrade/bluez/stage/usr/libexec/bluetooth/`:

```sh
strip=scratch/ingenic-toolchain-v5.2/toolchain/bin/mips-linux-gnu-strip
for d in bluetoothd obexd; do
  install -D -m 0755 scratch/base-upgrade/bluez/stage/usr/libexec/bluetooth/$d out/$d
  "$strip" out/$d
done
sha256sum out/bluetoothd out/obexd     # update firmware/ssc-overlay.sha256, upload both assets to build-inputs
```

The recipe builds through a relative source path, so the binaries contain no builder paths (the Ingenic GCC 5.2 has
no `-ffile-prefix-map`); the build fails if the build directory, the checkout or `$HOME` shows up in a daemon.
As with bluealsad, a rebuild is not guaranteed to be byte-identical. The patches change `bluetoothd` (endpoint
rediscovery when the remote connects, AVRCP cover-art advertisement) and `obexd` (cover-art-only build: Bluetooth
transport plus the BIP image-pull responder, no client or phonebook plugins).

## How v1.3.0 was assembled

* r1 / r3proii / r3ii_2025: `repack_upt.sh` on the staging base with the SSC overlay.
* V1: `repack_v1_upt.py` on the stock V1 image with the R1 image as resource/runtime source.
* The released players were later exchanged and relabelled with the tools in
  `scripts/firmware/package/history/`. `build_all_upt.sh` produces the same result directly.
