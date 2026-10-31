# Rebuilding the TempoTec V1 zram kernel candidate

This recipe rebuilds the V1 Linux 4.4.94+ kernel from the Ingenic X1600 SDK and the pinned HiBy kernel kit. It only builds the kernel. It does not build replacement vendor modules or package/flash a UPT.

## Pinned inputs

- Kernel kit: `https://github.com/Jepl4r/hiby-custom-kernel.git`, commit `4c7d47ede0bfa4b63528574817becc79d327bf9d` (clean checkout required). This kit is based on the pinned Ingenic SDK and adds patches 0016–0018 since the earlier `e1c5915` kit. The applied patch files and SHA-256 values are listed in `tempotec_v1-kernel-patches.sha256`.
- Ingenic SDK archive: `ingenic-linux-kernel4.4.94-x1600-v6.0-20240606.tar.bz2`, SHA-256 `3e8c101b7c12667dcfed888e2eda63cfa833c6e20f22569e2b646c40f8523641`.
- Stock input: official TempoTec V1 1.2 UPT, SHA-256 `9f929a92319a05a81bbd16cbf0fb8a886a9bb2def192f5a6786b6ea7032fa05d`.
- V1 vendor module imports/exports: `configs/tempotec_v1/stock-modules-need.txt` and `configs/tempotec_v1/stock-module-exports.txt`, derived from the 30 stock `/module_driver/*.ko` files. The kernel kit's `compare.py` reports 433 required kernel symbols and zero missing.
- Config fragments: `configs/tempotec_v1/tempotec_v1-required.config`, `tempotec_v1-parity.config`, `tempotec_v1-stock-compat.config`, and `tempotec_v1-zram.config`. The full final `.config` is also checked in as `tempotec_v1-final.config` (SHA-256 `beb5bccf91fa3299d177fc1de7e133687f4b456e2a0e1f2477dcf29b63ef7fa1`).
- Kernel-only harness delta: `tempotec_v1-kernel-only.patch` (SHA-256 `57ab67bf36be56e5931ab982bbe031715fcabf59753a98c11c800f9025624977`). It adds `--kernel-only`, saves `vmlinux`, and skips module builds. It applies cleanly to the pinned kit's `build.sh`.
- Compression: Python `zopfli==0.4.3`, `numiterations=15`; the x86_64 CPython 3.10+ ABI3 wheel SHA-256 is `769875152d0625c46707bcca57d4b2233fe653482067acd55fbf6ec525cb9bdc`.
- Build metadata: `KBUILD_BUILD_USER=root`, `KBUILD_BUILD_HOST=e564c422054b`, `KBUILD_BUILD_VERSION=1`, `KBUILD_BUILD_TIMESTAMP='Sat Oct 31 19:11:31 UTC 2026'`. Set `SOURCE_DATE_EPOCH=1793474132` for deterministic U-Boot image timestamps. The recorded build environment used the SDK's MIPS GCC 7.2.0 and Debian `mkimage` 2021.01.

## Build steps

Set `KIT_SOURCE`, `SDK_ARCHIVE`, `STOCK_V1_UPT`, and a new `WORK` directory. Use Podman or Docker with the kernel kit's `docker/Dockerfile`, plus `7z`, `unsquashfs`, and Python 3.10 or newer on the host.

Run the shell steps below with Bash (`set -euo pipefail`); the source-copy loop uses `read -d`.

```bash
git clone https://github.com/Jepl4r/hiby-custom-kernel.git "$KIT_SOURCE"
git -C "$KIT_SOURCE" checkout 4c7d47ede0bfa4b63528574817becc79d327bf9d
git -C "$KIT_SOURCE" status --porcelain   # must be empty
sha256sum "$SDK_ARCHIVE" "$STOCK_V1_UPT"

mkdir -p "$WORK/hiby-custom-kernel/boards/tempotec_v1"
git -C "$KIT_SOURCE" ls-files -z | while IFS= read -r -d '' f; do
  mkdir -p "$WORK/hiby-custom-kernel/$(dirname "$f")"
  cp -a "$KIT_SOURCE/$f" "$WORK/hiby-custom-kernel/$f"
done
patch -d "$WORK/hiby-custom-kernel" -p1 < firmware/kernel/tempotec_v1-kernel-only.patch
python3 "$WORK/hiby-custom-kernel/tools/extract-stock.py" tempotec_v1 "$STOCK_V1_UPT"
cp firmware/kernel/configs/tempotec_v1/stock-modules-need.txt \
  "$WORK/hiby-custom-kernel/boards/tempotec_v1/modules-need.txt"
cp firmware/kernel/configs/tempotec_v1/stock-module-exports.txt \
  "$WORK/hiby-custom-kernel/boards/tempotec_v1/hiby-exports.txt"
for f in tempotec_v1-required.config tempotec_v1-parity.config \
  tempotec_v1-stock-compat.config tempotec_v1-zram.config; do
  cp "firmware/kernel/configs/tempotec_v1/$f" "$WORK/hiby-custom-kernel/configs/$f"
done
```

Extract the stock modules for a repeatable ABI check with the repo helper. Run from the repository root:

```bash
python3 - "$STOCK_V1_UPT" "$WORK/v1-stock" <<'PY'
import importlib.util, pathlib, subprocess, sys
repo = pathlib.Path.cwd()
spec = importlib.util.spec_from_file_location("v1_repack", repo / "scripts/firmware/package/repack_v1_upt.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
work = pathlib.Path(sys.argv[2]); _, squashfs, _ = mod.extract_rootfs(pathlib.Path(sys.argv[1]), work / "extract")
root = work / "root"
subprocess.run(["unsquashfs", "-no-xattrs", "-d", str(root), str(squashfs)], check=True)
subprocess.run(["cp", "-a", str(root / "module_driver"), str(work / "module_driver")], check=True)
PY

for k in "$WORK/v1-stock/module_driver"/*.ko; do nm -u "$k"; done | awk 'NF {print $NF}' | sort -u > "$WORK/vendor-undefined.txt"
for k in "$WORK/v1-stock/module_driver"/*.ko; do nm "$k"; done | sed -n 's/.*__ksymtab_//p' | sort -u > "$WORK/vendor-exports.txt"
comm -23 "$WORK/vendor-undefined.txt" "$WORK/vendor-exports.txt" > "$WORK/hiby-modules-need.txt"
```

The resulting import list must match `configs/tempotec_v1/stock-modules-need.txt`; the export list must match `configs/tempotec_v1/stock-module-exports.txt`. Check with `cmp` after sorting/normalizing the checked-in files as needed. No replacement modules are built. `extract-stock.py` writes `boards/tempotec_v1/stock.dtb`; its SHA-256 must be `8e99b1a2a0b18c18ba4bfd7240689c570a629e665147249ac2d2095974b33751`.

Build the intermediate gzip image in the build container. `SDK_ARCHIVE` is mounted read-only; `/build` is a new, disposable build volume. For Podman, add `:Z` to the workspace and build-volume mounts as shown.

```bash
podman volume create tempotec-v1-kbuild
podman build --platform linux/amd64 -t hiby-custom-kernel "$WORK/hiby-custom-kernel/docker"
podman run --rm --platform linux/amd64 \
  -v "$WORK:/work:Z" \
  -v "$SDK_ARCHIVE:/work/$(basename "$SDK_ARCHIVE"):ro,Z" \
  -v tempotec-v1-kbuild:/build:Z \
  -e KBUILD_BUILD_USER=root -e KBUILD_BUILD_HOST=e564c422054b \
  -e KBUILD_BUILD_VERSION=1 \
  -e 'KBUILD_BUILD_TIMESTAMP=Sat Oct 31 19:11:31 UTC 2026' \
  -e SOURCE_DATE_EPOCH=1793474132 \
  hiby-custom-kernel bash /work/hiby-custom-kernel/build.sh \
    --model tempotec_v1 --name tempotec-v1-zram-candidate --jobs 8 \
    --fragment tempotec_v1-parity.config \
    --fragment tempotec_v1-stock-compat.config \
    --fragment tempotec_v1-zram.config --kernel-only
```

Generate the uncompressed kernel bytes using the SDK toolchain's `objcopy` (same flags as `arch/mips/boot/zcompressed/Makefile`):

```bash
podman run --rm --platform linux/amd64 \
  -v "$WORK:/work:Z" -v tempotec-v1-kbuild:/build:Z \
  -v "$SDK_ARCHIVE:/work/$(basename "$SDK_ARCHIVE"):ro,Z" \
  hiby-custom-kernel bash -lc '
    SDK=/build/sdk/ingenic-linux-kernel4.4.94-x1600-v6.0-20240606
    TOOL=$SDK/prebuilts/toolchains/mips-gcc720-glibc229/bin
    "$TOOL/mips-linux-gnu-objcopy" -O binary \
      --remove-section=.reginfo --remove-section=.mdebug --remove-section=.comment \
      --remove-section=.note --remove-section=.pdr --remove-section=.options \
      --remove-section=.MIPS.options /build/src/vmlinux \
      /work/hiby-custom-kernel/out/vmlinux.bin.raw
  '
```

Install the pinned Zopfli wheel in a host Python 3.10+ environment, verify its hash above, and compress the raw bytes exactly as follows:

```bash
python3 -m pip download --only-binary=:all: --no-deps --dest "$WORK/wheels" zopfli==0.4.3
sha256sum "$WORK/wheels"/*.whl   # must match the pinned wheel hash above
python3 -m venv "$WORK/zopfli-venv"
"$WORK/zopfli-venv/bin/pip" install --no-index --find-links "$WORK/wheels" zopfli==0.4.3
"$WORK/zopfli-venv/bin/python" - "$WORK/hiby-custom-kernel/out/vmlinux.bin.raw" <<'PY'
import pathlib, sys
from zopfli.gzip import compress
p = pathlib.Path(sys.argv[1])
p.with_suffix(p.suffix + ".gz").write_bytes(compress(p.read_bytes(), numiterations=15))
PY
```

Copy `vmlinux.bin.raw.gz` to `arch/mips/boot/zcompressed/vmlinux.bin.gz` in the existing `/build/src` tree. Relink only the zcompressed boot wrapper so Kbuild uses the Zopfli payload and its actual `IMAGESIZE`. Run this inside the build container; put the SDK toolchain first on `PATH`, replace the compressed payload, and remove stale dependent outputs so Kbuild regenerates the size-bearing header and wrapper. `-o` prevents rebuilding `vmlinux` or replacing the compressed payload with gzip:

```bash
cd /build/src
SDK=/build/sdk/ingenic-linux-kernel4.4.94-x1600-v6.0-20240606
export PATH="$SDK/prebuilts/toolchains/mips-gcc720-glibc229/bin:$PATH"
cp /work/hiby-custom-kernel/out/vmlinux.bin.raw.gz arch/mips/boot/zcompressed/vmlinux.bin.gz
rm -f arch/mips/boot/zcompressed/head.o arch/mips/boot/zcompressed/piggy.o \
  arch/mips/boot/zcompressed/vmlinuz arch/mips/boot/zcompressed/xImage
export KBUILD_BUILD_USER=root KBUILD_BUILD_HOST=e564c422054b KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP='Sat Oct 31 19:11:31 UTC 2026' SOURCE_DATE_EPOCH=1793474132
make -o vmlinux -o arch/mips/boot/zcompressed/vmlinux.bin.gz \
  ARCH=mips CROSS_COMPILE=mips-linux-gnu- 'HOSTCC=gcc -fcommon' -j8 xImage
```

Verify the resulting tracked artifacts with `sha256sum -c` using a checksum file containing the expected hashes recorded above and in `firmware/kernel/tempotec_v1.json`; also compare the relinked raw kernel, `.config`, `System.map`, `vmlinux`, and DTB hashes to that registry before accepting the xImage.

Copy the resulting `arch/mips/boot/zcompressed/xImage` over `out/xImage-tempotec-v1-zram-candidate`. The final image must have a valid U-Boot header and CRCs, contain the stock DTB byte-for-byte, and be no larger than the stock V1 xImage.

A clean rebuild of this documented recipe has not been independently replayed. The source, configuration, build metadata and shipped artifact hashes are recorded; container image and host-package versions are not fully pinned.

## Verified output

For the pinned inputs above, the final xImage is SHA-256 `bbad813b20f0c802b54bf2c9824e64539147a2311cde02a751a030f9a02b7384` (3,604,544 bytes; stock 3,731,520). The Zopfli stream decompresses to SHA-256 `8b3e179f8ebbb0fd345713e5d013b4b30372be6df8026fd53c3ecd43613afa0d`; the full `.config`, `System.map`, `vmlinux`, and DTB hashes are in `firmware/kernel/tempotec_v1.json`. All 433 required V1 module imports are exported. The kernel release is `4.4.94+`; zram is built in with LZ4.

The binary review also confirms the V1 DTB and ALSA rate table are byte-identical, all 201 power-supply property names remain in stock order, and five module-sensitive power-supply accessors have identical machine code. This is static validation only; no physical V1 was available for runtime testing.
