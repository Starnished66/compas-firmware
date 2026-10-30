#!/usr/bin/env python3
"""Host-only experimental TempoTec V1 repacker.

This tool only accepts the verified public V1 1.2 stock UPT and a marked,
static V1 MIPS32r2 Compas player. It preserves the stock kernel, update and
recovery payloads, copies the explicitly required Compas theme/font files and
the reviewed BlueALSA 5 SSC runtime, and changes only the two checked player
launch lines plus the exact legacy BlueALSA startup blocks in bt_init/bt_resume.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Iterable


# Single source of truth: firmware/inputs.sha256 (entry v1-stock.upt).
BASE_SHA256 = next(l.split()[0] for l in (pathlib.Path(__file__).resolve().parents[3] / "firmware/inputs.sha256").read_text().splitlines() if l.endswith("v1-stock.upt"))
BASE_MD5 = "d3301d3930309b5433331a2aed741652"
BASE_KERNEL_SHA256 = "3a83176b9d8da6c09eedd64348ea8a612ad5ee2ae532ce04ccadd7d0fa4bb25d"
R1_SSC_UPT_SHA256 = "43f55224db696391cdc650b77d276176a533505d88f98946d83f6eb5fa1bd8e9"
# Static-SSC BlueALSA daemon: single source of truth is firmware/ssc-overlay.sha256.
SSC_DAEMON_SHA256 = next(
    line.split()[0]
    for line in (pathlib.Path(__file__).resolve().parents[3] / "firmware/ssc-overlay.sha256").read_text().splitlines()
    if line.split()[-1:] == ["usr/bin/bluealsad"]
)
V1_MARKER = b"COMPAS_PLAYER_BOARD:tempotec_v1"
IMAGE_CHUNK_SIZE = 512 * 1024

# The compiled UI fonts and fallback faces are the files the current player
# opens by fixed path. Existing OEM Korean/Thai/default fonts stay untouched.
FONT_FILES = (
    "montserrat_12.bin", "montserrat_14.bin", "montserrat_16.bin",
    "montserrat_18.bin", "montserrat_20.bin", "montserrat_22.bin",
    "montserrat_24.bin", "montserrat_26.bin", "montserrat_28.bin",
    "montserrat_30.bin", "montserrat_32.bin", "montserrat_34.bin",
    "montserrat_40.bin", "unscii_16.bin", "Montserrat-Medium.ttf",
    "arabic.ttf", "chinese.ttf", "cjk_cyrillic.ttf", "emoji.ttf",
)

RUNTIME_FILES = (
    "usr/bin/bluealsad",
    "usr/bin/bluealsactl",
    "usr/lib/alsa-lib/libasound_module_pcm_bluealsa.so",
    "usr/lib/alsa-lib/libasound_module_ctl_bluealsa.so",
)

# The BlueZ 5.87 set of the R1 base. The two daemons come from the pinned runtime
# overlay (firmware/ssc-overlay.sha256); the rest are untouched files of the
# staging base r1.upt (firmware/inputs.sha256) and are pinned here.
OVERLAY_PINS_FILE = pathlib.Path(__file__).resolve().parents[3] / "firmware/ssc-overlay.sha256"
BLUEZ_OVERLAY_FILES = (
    "usr/libexec/bluetooth/bluetoothd",
    "usr/libexec/bluetooth/obexd",
)
BLUEZ_BASE_SHA256 = {
    "usr/bin/bluetoothctl": "c7827d6f19e803622cca2de4d1ea3b6300965863752f9c02d94966c3c5a00c17",
    "usr/bin/btmon": "77a9538fce2ef4412950520bab953ab408cb1588c53bec1fdf1c39d3ce2ae704",
    "usr/bin/hciconfig": "f048fb934eef02854dd275d78dc25010337337841633ae9122cbfb9a4bb38c4d",
    "usr/bin/hcitool": "9c5972aa72055788952bc83ecf1cf8eb8a7f046df8441017a4ae7cc4bd3803de",
    "usr/lib/libbluetooth.so.3.19.16": "21976de17255a7167fe671028f8294aefb2d96946086c05c019a99d7f3ac83cf",
}
# V1 main.conf: the R1 file (base file with the Compás name and BroadcomHighPriority = true set by
# clean_os.py), pinned, with V1's own DiscoverableTimeout = 0 (stay discoverable until the player turns
# it off) as the only difference.
R1_MAIN_CONF_SHA256 = "1781440d0389bac39f879a184aeb80f9e320a88360a2573f0f15aaedb0233582"
V1_MAIN_CONF_SHA256 = "a787d41320ef211f431d1bb4a0dc573617d620e280312b573b618aa820e0e603"
# libbluetooth: keep the old 3.19.2 file, point the SONAME and dev links at 3.19.16 like the R1 base.
OLD_V1_LIBBLUETOOTH_LINKS = {
    "usr/lib/libbluetooth.so": "libbluetooth.so.3.19.2",
    "usr/lib/libbluetooth.so.3": "libbluetooth.so.3.19.2",
}
NEW_LIBBLUETOOTH_LINKS = {
    "usr/lib/libbluetooth.so.3": "libbluetooth.so.3.19.16",
    "usr/lib/libbluetooth.so": "libbluetooth.so.3",
}
# Tracked files of this repository (firmware/overlay) shipped with the cover-art responder.
BLUEZ_TRACKED_FILES = (
    "etc/init.d/S81compas_obex",
    "etc/dbus-1/system.d/org.bluez.obex.conf",
    "etc/dbus-1/system.d/org.mpris.MediaPlayer2.compas.conf",
    "usr/share/licenses/bluez/NOTICE",
    "usr/share/licenses/bluez/COPYING",
    "usr/share/licenses/bluez/COPYING.LIB",
)
BLUEZ_ELF_FILES = (*BLUEZ_OVERLAY_FILES, "usr/bin/bluetoothctl", "usr/bin/btmon",
                   "usr/bin/hciconfig", "usr/bin/hcitool")

# BlueALSA 5.0 from the pinned R1 QA UPT uses GLib APIs added after the V1
# stock 2.62 runtime. Keep the old versioned files in place for existing V1
# consumers, and direct the GLib SONAME aliases to this pinned R1 2.84 family.
RUNTIME_LIBRARY_FILES = (
    "usr/lib/libglib-2.0.so.0.8400.4",
    "usr/lib/libgio-2.0.so.0.8400.4",
    "usr/lib/libgobject-2.0.so.0.8400.4",
    "usr/lib/libgmodule-2.0.so.0.8400.4",
    "usr/lib/libgthread-2.0.so.0.8400.4",
    "usr/lib/libffi.so.8.1.4",
    "usr/lib/libpcre2-8.so.0.14.0",
    "usr/lib/libasound.so.2.0.0",
)

RUNTIME_LIBRARY_SHA256 = {
    "usr/lib/libglib-2.0.so.0.8400.4": "f767029d5c6998cfb126d6655a90b5bc51c3f7df57bbbbf9c5816d3bdd28742d",
    "usr/lib/libgio-2.0.so.0.8400.4": "f95a2095b52e9f1407ddf4168acca1b3e01c45b17aca42669eb446ddc6ef5838",
    "usr/lib/libgobject-2.0.so.0.8400.4": "aa2e1dc970032ed7ba4494f662bdb20ba112022c16fa5a7bc467565fdbdc75b1",
    "usr/lib/libgmodule-2.0.so.0.8400.4": "c09d0a5da5d88d954ff13d65f4ef78263789026820ecf9f8d869d11319802d0f",
    "usr/lib/libgthread-2.0.so.0.8400.4": "f38131427adba592ffb8fae56217853fccdc535092300691723028e887157f5e",
    "usr/lib/libffi.so.8.1.4": "b98e3be041d00cbff0fdf934e714990de20f53a7ec7746b065fb7e754519072f",
    "usr/lib/libpcre2-8.so.0.14.0": "845b310e6e04615c3c7357f8e63eec5f9df29d23cf4907b52356f06d426ce5fc",
    "usr/lib/libasound.so.2.0.0": "aed04ac891336725c7d1d32005270415a52ae38fb26ff9a12389eeff184d0d8b",
}

OLD_GLIB_ALIAS_TARGETS = {
    "usr/lib/libglib-2.0.so.0": "libglib-2.0.so.0.6200.4",
    "usr/lib/libgio-2.0.so.0": "libgio-2.0.so.0.6200.4",
    "usr/lib/libgobject-2.0.so.0": "libgobject-2.0.so.0.6200.4",
    "usr/lib/libgmodule-2.0.so.0": "libgmodule-2.0.so.0.6200.4",
    "usr/lib/libgthread-2.0.so.0": "libgthread-2.0.so.0.6200.4",
}

RUNTIME_LIBRARY_ALIASES = {
    "usr/lib/libglib-2.0.so.0": "libglib-2.0.so.0.8400.4",
    "usr/lib/libgio-2.0.so.0": "libgio-2.0.so.0.8400.4",
    "usr/lib/libgobject-2.0.so.0": "libgobject-2.0.so.0.8400.4",
    "usr/lib/libgmodule-2.0.so.0": "libgmodule-2.0.so.0.8400.4",
    "usr/lib/libgthread-2.0.so.0": "libgthread-2.0.so.0.8400.4",
    "usr/lib/libffi.so.8": "libffi.so.8.1.4",
    "usr/lib/libpcre2-8.so.0": "libpcre2-8.so.0.14.0",
}

OLD_V1_LIBASOUND_SHA256 = "0bdef71700da1be2c3e7525ab45df90cdb8265cb41e1354a0a3e5e6cc61f08b4"
OLD_V1_LIBFFI7_SHA256 = "09848f8a94006fd1eac4f996e7de3857092e620ba94709f3c4b5a6fa97bc898e"
OLD_V1_LIBFFI7_ALIAS_TARGETS = {
    "usr/lib/libffi.so": "libffi.so.7.1.0",
    "usr/lib/libffi.so.7": "libffi.so.7.1.0",
}
OLD_V1_ALSA_ALIAS_TARGETS = {
    "usr/lib/libasound.so": "libasound.so.2.0.0",
    "usr/lib/libasound.so.2": "libasound.so.2.0.0",
}
OLD_V1_GLIB_SHA256 = {
    "usr/lib/libglib-2.0.so.0.6200.4": "ee20adc1448997901bb0d0632162d8dd8355544c580def6e0c76cc7226368376",
    "usr/lib/libgio-2.0.so.0.6200.4": "2778e61e201d4fb62b16ba77393f9ae33da5927d7172a41527d37484bd0ec76d",
    "usr/lib/libgobject-2.0.so.0.6200.4": "c7efe18b72be1cdc1f994ba2c09695b2e82b63383a73620b1d31d015e07e6d36",
    "usr/lib/libgmodule-2.0.so.0.6200.4": "e31aee5bb9caeec9e157f2b71f12eb835c4b9419c0eb6cb4cfe48c014068b8c2",
    "usr/lib/libgthread-2.0.so.0.6200.4": "b5d2c1742b3fecfbf56eecd410913a502c1f45ae0007f324cc6ed5e44dad439d",
}


class RepackError(RuntimeError):
    pass


def run(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RepackError(f"command failed ({exc.returncode}): {argv[0]}" + (f": {detail}" if detail else "")) from exc


def digest(path: pathlib.Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_regular(path: pathlib.Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RepackError(f"{label} must be a regular file: {path}")


def require_v1_marker(data: bytes) -> None:
    if V1_MARKER not in data:
        raise RepackError("player lacks exact COMPAS_PLAYER_BOARD:tempotec_v1 marker")


def board_from_config(config_path: pathlib.Path) -> tuple[str, tuple[int, int]]:
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RepackError("stock V1 config.json is unreadable") from exc
    if not isinstance(config, list):
        raise RepackError("stock config.json has an unexpected top-level shape")
    product = next((item for item in config if isinstance(item, dict) and item.get("type") == "product"), None)
    screen = next((item for item in config if isinstance(item, dict) and item.get("type") == "screen"), None)
    if not product or not screen:
        raise RepackError("stock config.json lacks product/screen records")
    device = product.get("device")
    dimensions = (screen.get("hor"), screen.get("ver"))
    if device != "V1" or dimensions != (240, 320):
        raise RepackError(f"refusing non-V1 base: device={device!r}, screen={dimensions!r}")
    return device, dimensions


def validate_player(path: pathlib.Path) -> dict[str, object]:
    safe_regular(path, "player")
    require_v1_marker(path.read_bytes())
    data = path.read_bytes()[:64]
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise RepackError("player is not ELF32 little-endian")
    e_type, machine = struct.unpack_from("<HH", data, 16)
    flags = struct.unpack_from("<I", data, 36)[0]
    if e_type != 2 or machine != 8 or (flags & 0xF0000000) != 0x70000000 or (flags & 0xF000) != 0x1000:
        raise RepackError("player must be a MIPS32r2 O32 executable")
    dynamic = run(["readelf", "-l", str(path)], capture=True).stdout
    needed = run(["readelf", "-d", str(path)], capture=True).stdout
    if "Requesting program interpreter" in dynamic or "(NEEDED)" in needed:
        raise RepackError("player must be statically linked; dynamic dependencies are not permitted for V1")
    return {"sha256": digest(path), "size_bytes": path.stat().st_size, "elf": "ELF32 MIPS32r2 O32 static", "board_marker": V1_MARKER.decode()}


def parse_ota_metadata(path: pathlib.Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}

    def commit() -> None:
        nonlocal current
        if not current:
            return
        kind = current.get("img_type", "")
        if not kind and set(current) == {"ota_version"}:
            current = {}
            return
        if not kind or kind in result:
            raise RepackError("OTA metadata has a missing or duplicate img_type")
        result[kind] = current
        current = {}

    for raw in path.read_text().splitlines() + [""]:
        line = raw.strip()
        if not line:
            commit()
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == "img_type" and "img_type" in current:
                commit()
            current[key.strip()] = value.strip()
    return result


def verify_image_chunks(ota: pathlib.Path, kind: str, expected_name: str, out: pathlib.Path) -> dict[str, object]:
    metadata = parse_ota_metadata(ota / "ota_update.in")
    info = metadata.get(kind)
    if not info or info.get("img_name") != expected_name:
        raise RepackError(f"OTA metadata has no {kind} image named {expected_name}")
    try:
        size = int(info["img_size"])
        image_md5 = info["img_md5"].lower()
    except (KeyError, ValueError) as exc:
        raise RepackError(f"invalid size/MD5 metadata for {expected_name}") from exc
    if size <= 0 or not re.fullmatch(r"[0-9a-f]{32}", image_md5):
        raise RepackError(f"invalid size/MD5 metadata for {expected_name}")
    chain_path = ota / f"ota_md5_{expected_name}.{image_md5}"
    safe_regular(chain_path, "image MD5 chain")
    chain = [line.strip().lower() for line in chain_path.read_text().splitlines() if line.strip()]
    chunks = sorted(ota.glob(f"{expected_name}.[0-9][0-9][0-9][0-9].*") )
    if not chain or len(chunks) != len(chain):
        raise RepackError(f"chunk chain count mismatch for {expected_name}")
    full_md5 = hashlib.md5()
    written = 0
    previous = image_md5
    with out.open("wb") as target:
        for index, chunk in enumerate(chunks):
            safe_regular(chunk, "image chunk")
            match = re.fullmatch(re.escape(expected_name) + r"\.(\d{4})\.([0-9a-f]{32})", chunk.name)
            if not match or int(match.group(1)) != index or match.group(2) != previous:
                raise RepackError(f"broken image chunk numbering/hash link: {chunk.name}")
            part_md5 = hashlib.md5()
            part_size = 0
            with chunk.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
                    part_md5.update(block)
                    full_md5.update(block)
                    part_size += len(block)
            actual_part = part_md5.hexdigest()
            if actual_part != chain[index]:
                raise RepackError(f"chunk MD5 mismatch: {chunk.name}")
            if part_size <= 0 or part_size > IMAGE_CHUNK_SIZE or (index < len(chunks) - 1 and part_size != IMAGE_CHUNK_SIZE):
                raise RepackError(f"invalid image chunk size: {chunk.name}")
            previous = actual_part
            written += part_size
    if written != size or full_md5.hexdigest() != image_md5:
        raise RepackError(f"aggregate size/MD5 mismatch for {expected_name}")
    return {"size_bytes": size, "md5": image_md5, "sha256": digest(out), "chunks": len(chunks)}


def validate_upt_archive(path: pathlib.Path) -> None:
    safe_regular(path, "UPT")
    listing = run(["7z", "l", "-slt", str(path)], capture=True).stdout
    seen: set[str] = set()
    for block in re.split(r"\n\s*\n", listing):
        fields = {}
        for line in block.splitlines():
            if " = " in line:
                key, value = line.split(" = ", 1)
                fields[key] = value
        name = fields.get("Path")
        if not name or fields.get("Type") in {"Iso", "Folder"}:
            continue
        pure = pathlib.PurePosixPath(name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or name in seen:
            raise RepackError(f"unsafe or duplicate UPT member path: {name}")
        if fields.get("Symbolic Link") or fields.get("Hard Link"):
            raise RepackError(f"linked UPT member is not accepted: {name}")
        seen.add(name)
    run(["7z", "t", str(path)])


def extract_rootfs(upt: pathlib.Path, work: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, dict[str, object]]:
    work.mkdir(parents=True, exist_ok=True)
    unpack = work / "outer"
    unpack.mkdir()
    run(["7z", "x", "-y", "-o" + str(unpack), str(upt)])
    ota = unpack / "ota_v0"
    if not (ota / "ota_v0.ok").is_file():
        raise RepackError("UPT lacks ota_v0.ok")
    images = parse_ota_metadata(ota / "ota_update.in")
    if set(images) != {"kernel", "rootfs"}:
        raise RepackError("V1 UPT must contain exactly kernel and rootfs image entries")
    kernel = work / "xImage"
    rootfs = work / "rootfs.squashfs"
    kernel_info = verify_image_chunks(ota, "kernel", "xImage", kernel)
    root_info = verify_image_chunks(ota, "rootfs", "rootfs.squashfs", rootfs)
    return ota, rootfs, {"xImage": kernel_info, "rootfs.squashfs": root_info}


def patch_launcher_text(text: str) -> str:
    old = "/usr/bin/hiby_player"
    new = "/usr/bin/compas_player"
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.strip() == old]
    if len(matches) != 1:
        raise RepackError("stock hiby_player.sh must contain exactly one active /usr/bin/hiby_player command")
    i = matches[0]
    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    ending = "\r\n" if lines[i].endswith("\r\n") else "\n" if lines[i].endswith("\n") else ""
    lines[i] = indent + new + ending
    return "".join(lines)


OLD_BLUEALSA_BLOCK = (
    'if ! pgrep "bluealsa" > /dev/null; then\n'
    '    /usr/bin/bluealsa -p a2dp-source --a2dp-volume &\n'
    'fi\n'
)
NEW_BLUEALSA_COMMENT = "# Compas starts the BlueALSA 5 source daemon on demand.\n"
OLD_BT_INIT_BLUEALSA_LAUNCH = "/usr/bin/bluealsa -p a2dp-source --a2dp-volume &\n"


def patch_bt_resume_text(text: str) -> str:
    if text.count(OLD_BLUEALSA_BLOCK) != 1:
        raise RepackError("stock bt_resume legacy BlueALSA block changed; refusing to patch unexpected content")
    return text.replace(OLD_BLUEALSA_BLOCK, NEW_BLUEALSA_COMMENT, 1)


def patch_bt_init_text(text: str) -> str:
    if text.count(OLD_BT_INIT_BLUEALSA_LAUNCH) != 1:
        raise RepackError("stock bt_init must contain exactly one expected legacy BlueALSA launch")
    active_legacy = re.findall(r"(?m)^[ \t]*/usr/bin/bluealsa(?:[ \t]|$).*?(?:\n|$)", text)
    if len(active_legacy) != 1 or active_legacy[0] != OLD_BT_INIT_BLUEALSA_LAUNCH:
        raise RepackError("stock bt_init contains an unexpected or duplicate active legacy BlueALSA command")
    patched = text.replace(OLD_BT_INIT_BLUEALSA_LAUNCH, NEW_BLUEALSA_COMMENT, 1)
    if re.search(r"(?m)^[ \t]*/usr/bin/bluealsa(?:[ \t]|$)", patched):
        raise RepackError("legacy BlueALSA startup command remains active in bt_init")
    return patched


def replace_script(path: pathlib.Path, backup_path: pathlib.Path, transform) -> dict[str, str]:
    safe_regular(path, "stock shell script")
    if backup_path.exists() or backup_path.is_symlink():
        raise RepackError(f"OEM restore backup path already exists: {backup_path}")
    original = path.read_bytes()
    try:
        updated_text = transform(original.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RepackError(f"shell script is not UTF-8 text: {path}") from exc
    updated = updated_text.encode("utf-8")
    if updated == original:
        raise RepackError(f"expected launcher edit did not change {path}")
    shutil.copy2(path, backup_path)
    path.write_bytes(updated)
    path.chmod(path.stat().st_mode | 0o111)
    run(["sh", "-n", str(path)])
    return {"original_sha256": hashlib.sha256(original).hexdigest(), "patched_sha256": digest(path), "backup": str(backup_path)}


def check_elf_compatibility(path: pathlib.Path, base_root: pathlib.Path, supplied_sonames: Iterable[str]) -> dict[str, object]:
    """Validate MIPS32r2 dynamic binaries and close their dependency names."""
    info = path.read_bytes()[:64]
    if len(info) < 52 or info[:7] != b"\x7fELF\x01\x01\x01":
        raise RepackError(f"runtime file is not ELF32 little-endian: {path}")
    e_type, machine = struct.unpack_from("<HH", info, 16)
    flags = struct.unpack_from("<I", info, 36)[0]
    if e_type not in {2, 3} or machine != 8 or (flags & 0xF0000000) != 0x70000000 or (flags & 0xF000) != 0x1000:
        raise RepackError(f"runtime ELF is not MIPS32r2: {path}")
    program = run(["readelf", "-l", str(path)], capture=True).stdout
    if e_type == 2 and "Requesting program interpreter: /lib/ld.so.1" not in program:
        raise RepackError(f"runtime executable requests an unexpected interpreter: {path}")
    if e_type == 3 and "Requesting program interpreter" in program:
        raise RepackError(f"runtime shared object unexpectedly has an interpreter: {path}")
    dynamic = run(["readelf", "-d", str(path)], capture=True).stdout
    needed = re.findall(r"Shared library: \[([^]]+)\]", dynamic)
    supplied = set(supplied_sonames)
    missing = []
    for lib in needed:
        if lib in {"libc.so.6", "libm.so.6", "libpthread.so.0", "librt.so.1", "libdl.so.2"}:
            continue
        if not any((base_root / directory / lib).exists() for directory in ("lib", "usr/lib", "usr/lib64")) and lib not in supplied:
            missing.append(lib)
    if missing:
        raise RepackError(f"runtime dependency closure is incomplete for {path.name}: {', '.join(sorted(missing))}")
    versions = run(["readelf", "--version-info", str(path)], capture=True).stdout
    candidate_glibc = [tuple(map(int, m)) for m in re.findall(r"Name: GLIBC_(\d+)\.(\d+)", versions)]
    stock_libc = base_root / "lib/libc.so.6"
    if stock_libc.exists():
        stock_versions = run(["readelf", "--version-info", str(stock_libc)], capture=True).stdout
        libc_versions = [tuple(map(int, m)) for m in re.findall(r"Name: GLIBC_(\d+)\.(\d+)", stock_versions)]
        if candidate_glibc and libc_versions and max(candidate_glibc) > max(libc_versions):
            raise RepackError(f"runtime requires newer GLIBC than V1 provides: {path.name}")
    return {"sha256": digest(path), "needed": needed, "missing": missing,
            "max_required_glibc": ".".join(map(str, max(candidate_glibc))) if candidate_glibc else None}


def resolve_image_path(root: pathlib.Path, image_path: str) -> pathlib.Path | None:
    """Resolve absolute/relative ELF paths without following absolute links on the host."""
    current = root / image_path.lstrip("/") if image_path.startswith("/") else root / image_path
    seen = set()
    for _ in range(40):
        try:
            rel = current.relative_to(root).as_posix()
        except ValueError:
            return None
        if rel in seen:
            return None
        seen.add(rel)
        if not current.is_symlink():
            return current if current.exists() else None
        target = os.readlink(current)
        current = root / target.lstrip("/") if target.startswith("/") else current.parent / target
        parts = []
        for part in current.relative_to(root).parts:
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        current = root.joinpath(*parts)
    return None


def elf_dynamic_symbols(path: pathlib.Path) -> tuple[list[tuple[str, str | None]], list[tuple[str, str | None]]]:
    """Return defined and strong undefined dynamic symbol names/versions."""
    output = run(["readelf", "--dyn-syms", "-W", str(path)], capture=True).stdout
    defined: list[tuple[str, str | None]] = []
    undefined: list[tuple[str, str | None]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].endswith(":") or not fields[0][:-1].isdigit():
            continue
        binding, index, raw_name = fields[4], fields[6], fields[7]
        if index == "UND":
            if binding == "WEAK" or raw_name == "":
                continue
            destination = undefined
        else:
            if binding not in {"GLOBAL", "WEAK", "GNU_UNIQUE"} or raw_name == "":
                continue
            destination = defined
        name, separator, version = raw_name.partition("@")
        destination.append((name, version.lstrip("@") if separator else None))
    return defined, undefined


def check_runtime_strong_symbol_closure(root: pathlib.Path, entrypoints: Iterable[str]) -> dict[str, object]:
    """Check each executable's imports against only its own transitive ELF closure."""
    entrypoints = list(entrypoints)
    all_objects: set[str] = set()
    unresolved_libraries = []
    unresolved_symbols = []
    for entrypoint in entrypoints:
        queue = [entrypoint]
        objects: dict[str, pathlib.Path] = {}
        while queue:
            image_path = queue.pop(0)
            path = resolve_image_path(root, "/" + image_path.lstrip("/"))
            if path is None:
                unresolved_libraries.append({"entrypoint": entrypoint, "object": image_path,
                                            "missing": "entrypoint or symlink target"})
                continue
            rel = path.relative_to(root).as_posix()
            if rel in objects:
                continue
            dynamic = run(["readelf", "-d", str(path)], capture=True).stdout
            if not dynamic:
                continue
            objects[rel] = path
            interp = re.search(r"Requesting program interpreter: ([^]]+)", run(["readelf", "-l", str(path)], capture=True).stdout)
            if interp:
                loader = resolve_image_path(root, interp.group(1))
                if loader is None:
                    unresolved_libraries.append({"entrypoint": entrypoint, "object": rel,
                                                "missing": "interpreter " + interp.group(1)})
                else:
                    queue.append(loader.relative_to(root).as_posix())
            for soname in re.findall(r"Shared library: \[([^]]+)\]", dynamic):
                provider = None
                for directory in ("lib", "usr/lib", "usr/lib64", "usr/local/lib"):
                    provider = resolve_image_path(root, "/" + directory + "/" + soname)
                    if provider is not None:
                        break
                if provider is None:
                    unresolved_libraries.append({"entrypoint": entrypoint, "object": rel,
                                                "missing": soname})
                else:
                    queue.append(provider.relative_to(root).as_posix())

        exports: set[tuple[str, str | None]] = set()
        undefined_by_object: dict[str, list[tuple[str, str | None]]] = {}
        for rel, path in objects.items():
            defined, undefined = elf_dynamic_symbols(path)
            exports.update(defined)
            undefined_by_object[rel] = undefined
        exported_names = {name for name, _ in exports}
        for rel, undefined in undefined_by_object.items():
            all_objects.add(rel)
            for name, version in undefined:
                found = ((name, version) in exports) if version else (name in exported_names)
                if not found:
                    unresolved_symbols.append({"entrypoint": entrypoint, "object": rel,
                                               "symbol": name, "version": version})
    return {
        "entrypoints": entrypoints,
        "resolved_elf_objects": len(all_objects),
        "unresolved_libraries": unresolved_libraries,
        "unresolved_strong_symbols": unresolved_symbols,
        "closed": not unresolved_libraries and not unresolved_symbols,
    }


def copy_explicit_file(src: pathlib.Path, dest: pathlib.Path, label: str) -> dict[str, object]:
    safe_regular(src, label)
    if dest.exists() or dest.is_symlink():
        raise RepackError(f"refusing to replace existing destination without backup: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return {"path": str(dest), "sha256": digest(dest), "size_bytes": dest.stat().st_size}


def install_runtime_library_overlay(r1_root: pathlib.Path, v1_root: pathlib.Path) -> dict[str, object]:
    """Install the pinned R1 GLib/ALSA family needed by BlueALSA 5 on V1."""
    for rel, expected in OLD_V1_GLIB_SHA256.items():
        path = v1_root / rel
        safe_regular(path, "stock V1 GLib rollback file")
        if digest(path) != expected:
            raise RepackError("unexpected stock V1 GLib rollback file: " + rel)
    for rel, expected_target in OLD_GLIB_ALIAS_TARGETS.items():
        alias = v1_root / rel
        if not alias.is_symlink() or os.readlink(alias) != expected_target:
            raise RepackError("unexpected stock V1 GLib SONAME alias: " + rel)
    for rel, expected_target in OLD_V1_LIBFFI7_ALIAS_TARGETS.items():
        alias = v1_root / rel
        if not alias.is_symlink() or os.readlink(alias) != expected_target:
            raise RepackError("stock V1 libffi7 compatibility alias changed: " + rel)
    old_ffi7 = v1_root / "usr/lib/libffi.so.7.1.0"
    safe_regular(old_ffi7, "stock V1 libffi7")
    if digest(old_ffi7) != OLD_V1_LIBFFI7_SHA256:
        raise RepackError("stock V1 libffi7 file differs from its pinned rollback content")
    for rel, expected_target in OLD_V1_ALSA_ALIAS_TARGETS.items():
        alias = v1_root / rel
        if not alias.is_symlink() or os.readlink(alias) != expected_target:
            raise RepackError("stock V1 ALSA SONAME alias changed: " + rel)

    source_asound = r1_root / "usr/lib/libasound.so.2.0.0"
    safe_regular(source_asound, "pinned R1 ALSA runtime")
    if digest(source_asound) != RUNTIME_LIBRARY_SHA256["usr/lib/libasound.so.2.0.0"]:
        raise RepackError("R1 ALSA runtime differs from the pinned donor hash")
    target_asound = v1_root / "usr/lib/libasound.so.2.0.0"
    safe_regular(target_asound, "stock V1 ALSA runtime")
    if digest(target_asound) != OLD_V1_LIBASOUND_SHA256:
        raise RepackError("stock V1 ALSA runtime differs from the pinned base hash")

    installed: dict[str, object] = {}
    for rel in RUNTIME_LIBRARY_FILES:
        src = r1_root / rel
        safe_regular(src, "pinned R1 BlueALSA runtime dependency")
        expected = RUNTIME_LIBRARY_SHA256[rel]
        if digest(src) != expected:
            raise RepackError("R1 runtime dependency differs from the pinned donor hash: " + rel)
        dest = v1_root / rel
        if rel == "usr/lib/libasound.so.2.0.0":
            # The stock .so and .so.2 aliases already target this exact path.
            shutil.copy2(src, dest)
            if digest(dest) != expected:
                raise RepackError("installed R1 ALSA runtime hash mismatch")
            installed[rel] = {"sha256": digest(dest), "replaced_stock_sha256": OLD_V1_LIBASOUND_SHA256}
            continue
        if dest.exists() or dest.is_symlink():
            raise RepackError("V1 already contains an unexpected new runtime version: " + rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        if digest(dest) != expected:
            raise RepackError("copied R1 runtime dependency hash mismatch: " + rel)
        installed[rel] = {"sha256": digest(dest), "size_bytes": dest.stat().st_size}

    aliases = {}
    for rel, target in RUNTIME_LIBRARY_ALIASES.items():
        donor_alias = r1_root / rel
        if not donor_alias.is_symlink() or os.readlink(donor_alias) != target:
            raise RepackError("R1 runtime SONAME alias differs from the pinned target: " + rel)
        dest = v1_root / rel
        if rel in OLD_GLIB_ALIAS_TARGETS:
            if not dest.is_symlink() or os.readlink(dest) != OLD_GLIB_ALIAS_TARGETS[rel]:
                raise RepackError("stock V1 GLib alias changed before replacement: " + rel)
            dest.unlink()
        elif dest.exists() or dest.is_symlink():
            raise RepackError("V1 already contains unexpected runtime SONAME alias: " + rel)
        dest.symlink_to(target)
        aliases[rel] = {"target": target, "sha256": digest(dest)}

    # Keep V1's old GLib implementation, libffi7, its generic libffi.so link,
    # and ALSA link topology available for legacy consumers and rollback.
    preserved = {}
    for rel in (*OLD_V1_GLIB_SHA256, "usr/lib/libffi.so.7.1.0", *OLD_V1_LIBFFI7_ALIAS_TARGETS, *OLD_V1_ALSA_ALIAS_TARGETS):
        path = v1_root / rel
        preserved[rel] = {"sha256": digest(path) if path.is_file() and not path.is_symlink() else None,
                          "symlink": os.readlink(path) if path.is_symlink() else None}
    if os.readlink(v1_root / "usr/lib/libffi.so") != "libffi.so.7.1.0":
        raise RepackError("generic V1 libffi.so alias must remain on ABI 7")

    checked = {}
    for rel in (*RUNTIME_FILES, *RUNTIME_LIBRARY_FILES):
        path = v1_root / rel
        checked[rel] = check_elf_compatibility(path, v1_root, set())
    closure = check_runtime_strong_symbol_closure(v1_root, (*RUNTIME_FILES, *RUNTIME_LIBRARY_FILES))
    if not closure["closed"]:
        sample = closure["unresolved_strong_symbols"][:8] or closure["unresolved_libraries"][:8]
        raise RepackError("BlueALSA runtime has unresolved strong ELF imports after the approved V1 overlay: " + repr(sample))
    return {"files": installed, "aliases": aliases, "preserved_stock_abi": preserved,
            "libffi_generic_alias_unchanged": "libffi.so.7.1.0", "elf_compatibility": checked,
            "strong_symbol_closure": closure}


def copy_theme_and_fonts(r1_root: pathlib.Path, v1_root: pathlib.Path) -> dict[str, object]:
    source_theme = r1_root / "usr/resource/litegui/theme2"
    target_theme = v1_root / "usr/resource/litegui/theme2"
    if target_theme.exists() or target_theme.is_symlink():
        raise RepackError("V1 stock image unexpectedly already has theme2; refusing to overwrite OEM assets")
    if not source_theme.is_dir() or source_theme.is_symlink():
        raise RepackError("approved R1 candidate has no regular theme2 directory")
    theme_files = []
    for p in source_theme.rglob("*"):
        if p.is_symlink():
            raise RepackError(f"theme asset is a symlink: {p.relative_to(source_theme)}")
        if p.is_file():
            theme_files.append(p)
    if not theme_files:
        raise RepackError("approved theme2 is empty")
    shutil.copytree(source_theme, target_theme)

    font_source = r1_root / "usr/resource/fonts"
    font_target = v1_root / "usr/resource/fonts"
    if not font_target.is_dir() or font_target.is_symlink():
        raise RepackError("V1 stock fonts directory is missing or linked")
    installed = {}
    for name in FONT_FILES:
        src = font_source / name
        safe_regular(src, "required Compas font")
        dst = font_target / name
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink() or not dst.is_file():
                raise RepackError(f"unsafe OEM font path: {dst}")
            # Preserve existing OEM language/fallback assets. Compas's binary
            # font files are checked byte-for-byte because the player embeds
            # their manifest hashes; other fallback files are added only when
            # absent.
            if name.endswith(".bin") and digest(dst) != digest(src):
                raise RepackError(f"OEM font conflicts with the player manifest: {name}")
            installed[name] = {"sha256": digest(dst), "source": "preserved OEM"}
            continue
        shutil.copy2(src, dst)
        installed[name] = {"sha256": digest(dst), "source": "approved R1 candidate"}
    return {"theme2_file_count": len(theme_files), "theme2_sha256_tree": tree_hash(target_theme), "fonts": installed}


def tree_hash(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix().encode()
        if p.is_symlink():
            raise RepackError(f"symlink not allowed in copied asset tree: {p}")
        if p.is_file():
            h.update(rel + b"\0" + digest(p).encode() + b"\0")
    return h.hexdigest()


def tree_inventory(root: pathlib.Path) -> dict[str, tuple[str, int, str]]:
    inventory: dict[str, tuple[str, int, str]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode & 0o7777
        if path.is_symlink():
            inventory[rel] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            inventory[rel] = ("directory", mode, "")
        elif path.is_file():
            inventory[rel] = ("file", mode, digest(path))
        else:
            inventory[rel] = ("other", mode, "")
    return inventory


def verify_only_allowed_changes(before: dict[str, tuple[str, int, str]], after: dict[str, tuple[str, int, str]], asset_paths=()) -> list[str]:
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    exact = {
        "usr/bin/hiby_player", "usr/bin/hiby_player.oem", "usr/bin/compas_player",
        "usr/bin/hiby_player.sh", "usr/bin/hiby_player.sh.oem",
        "usr/resource/fonts/default.otf", "usr/resource/fonts/msyh.ttf",
        "usr/lib/libspeexdsp.so.1.5.2", "usr/lib/libspeexdsp.so.1",
        "usr/lib/alsa-lib/libasound_module_rate_speexrate.so",
        "usr/lib/alsa-lib/libasound_module_rate_speexrate_best.so",
        "usr/lib/alsa-lib/libasound_module_rate_speexrate_medium.so",
        "usr/bin/bt_init", "usr/bin/bt_init.oem",
        "usr/bin/bt_resume", "usr/bin/bt_resume.oem",
        "usr/bin/bluealsad", "usr/bin/bluealsactl",
        "usr/lib/alsa-lib/libasound_module_pcm_bluealsa.so",
        "usr/lib/alsa-lib/libasound_module_ctl_bluealsa.so",
        "usr/lib/alsa-lib/stock-v1",
        "usr/lib/alsa-lib/stock-v1/libasound_module_pcm_bluealsa.so",
        "usr/lib/alsa-lib/stock-v1/libasound_module_ctl_bluealsa.so",
        "usr/lib/libopenaptx.so.0", "usr/lib/libopenaptx.so.0.2.0",
        "usr/resource/litegui/theme2",
    }
    exact.update(RUNTIME_LIBRARY_FILES)
    exact.update(RUNTIME_LIBRARY_ALIASES)
    exact.update(f"usr/resource/fonts/{name}" for name in FONT_FILES)
    for name in asset_paths:
        exact.add(name)
        exact.update(str(parent) for parent in pathlib.PurePosixPath(name).parents if str(parent) != ".")
    prefixes = ("usr/resource/litegui/theme2/",)
    unexpected = [key for key in changed if key not in exact and not key.startswith(prefixes)]
    if unexpected:
        raise RepackError("rootfs changed outside the explicit V1 player/runtime/assets allowlist: " + ", ".join(unexpected[:12]))
    return changed


LEGACY_FILES = {
    "usr/bin/hiby_player.oem": "920ec0fab1d965ee6abf92b6fd38eec6a7de088f8a8185a8045752db34cb3c80",
    "usr/resource/fonts/default.otf": "f3e035dbcb69d828d6b61f9ea42f87f361977252ec398b8afaed484b50723472",
    "usr/resource/fonts/msyh.ttf": "812f6f8226abe75ef135418ed19b54084da46e0fe067809be06841b5b282bcae",
}


def remove_unused_oem_files(root: pathlib.Path) -> dict[str, str]:
    # These exact stock files are used only by the inactive OEM player.
    # The pinned official firmware remains the recovery/rollback source.
    for rel, expected in LEGACY_FILES.items():
        path = root / rel
        safe_regular(path, "unused OEM file")
        if digest(path) != expected:
            raise RepackError("unexpected unused OEM file hash: " + rel)
    for rel in LEGACY_FILES:
        (root / rel).unlink()
    return dict(LEGACY_FILES)


ASSET_REPO = pathlib.Path(__file__).resolve().parents[3]
USB_OVERLAY_ASSET = "assets/v1/theme2/usb/usb.png"
USB_OVERLAY_SHA256 = "fb7c7e98ce1efb7ef33f341c508e09c0110c1e09093cea7a960860266662c434"


def copy_current_assets(root: pathlib.Path) -> dict[str, object]:
    # Use the same tracked shared assets as the normal HiBy repacker.
    tracked = run(["git", "-C", str(ASSET_REPO), "ls-files", "assets/theme1", "assets/theme2", "assets/fonts"], capture=True).stdout.splitlines()
    mappings = (("assets/theme1/", "usr/resource/litegui/theme1/"),
                ("assets/theme2/", "usr/resource/litegui/theme2/"),
                ("assets/fonts/", "usr/resource/fonts/"))
    copied = {}
    for rel in tracked:
        # Store layouts intentionally stay downloadable, as on HiBy images.
        name = pathlib.PurePosixPath(rel).name
        if "/player_layouts/" in rel and any(name == key + ext or name.startswith(key + "@") or name.startswith(key + "_") for key in ("vinyl", "Hibys", "HibysGraph") for ext in (".xml", ".png")):
            continue
        for prefix, dest in mappings:
            if not rel.startswith(prefix):
                continue
            target_rel = dest + rel[len(prefix):]
            source, target = ASSET_REPO / rel, root / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            if source.is_symlink():
                link = os.readlink(source)
                if pathlib.PurePosixPath(link).is_absolute() or ".." in pathlib.PurePosixPath(link).parts:
                    raise RepackError("unsafe tracked asset symlink: " + rel)
                if target.exists():
                    target.unlink()
                target.symlink_to(link)
                copied[target_rel] = {"symlink": link}
            else:
                safe_regular(source, "tracked asset")
                shutil.copy2(source, target)
                copied[target_rel] = {"sha256": digest(source)}
            break
    return copied


def clean_new_os(root: pathlib.Path) -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("compas_clean_os", ASSET_REPO / "scripts/firmware/package/clean_os.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare(root, ASSET_REPO)


def install_required_usb_overlay(root: pathlib.Path) -> dict[str, object]:
    """Restore the pinned 150px V1 overlay icon after tracked-asset cleanup."""
    source = ASSET_REPO / USB_OVERLAY_ASSET
    safe_regular(source, "canonical stock USB DAC overlay asset")
    if digest(source) != USB_OVERLAY_SHA256:
        raise RepackError("canonical stock USB DAC overlay differs from its pinned hash")
    rel = "usr/resource/litegui/theme2/usb/usb.png"
    target = root / rel
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise RepackError("unsafe USB DAC overlay destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if digest(target) != USB_OVERLAY_SHA256:
        raise RepackError("installed USB DAC overlay failed its pinned hash check")
    return {rel: {"sha256": USB_OVERLAY_SHA256}}


# Panel-sized (240x320) boot artwork. The shared theme2 splash is 480x800. The V1 splash script
# picks etc/logo.jpeg, logo1.jpeg or logo2.jpeg from a NAND theme flag; all three carry the same
# splash. Provenance: assets/boot-artwork-source.txt (the per-board folders hold only
# installable files, so it lives beside usb-overlay-source.txt).
V1_BOOT_ARTWORK = {
    "etc/logo.jpeg": ("JPEG", "assets/v1/etc/logo.jpeg"),
    "etc/logo1.jpeg": ("JPEG", "assets/v1/etc/logo1.jpeg"),
    "etc/logo2.jpeg": ("JPEG", "assets/v1/etc/logo2.jpeg"),
    "usr/resource/litegui/theme2/boot_animation/en/0.jpg": ("JPEG", "assets/v1/theme2/boot_animation/en/0.jpg"),
    "usr/resource/litegui/theme2/boot_animation/en/0.png": ("PNG", "assets/v1/theme2/boot_animation/en/0.png"),
}
V1_BOOT_ARTWORK_SHA256 = {
    "JPEG": "dab3711574f46254ad30119c90bfef1731362f4359563bf33cb1cc08529919b6",
    "PNG": "77552121c451ad33e7e4cdf88d1615be210430173e8bc834b49f788241d44cfb",
}
V1_PANEL = (240, 320)


def image_format_and_size(data: bytes) -> tuple[str, int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return "PNG", width, height
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 0xFF:
                return None
            marker = data[pos + 1]
            if marker == 0xFF:
                pos += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2) and pos + 9 <= len(data):
                height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
                return "JPEG", width, height
            pos += 2 + length
    return None


def install_v1_boot_artwork(root: pathlib.Path) -> dict[str, object]:
    """Install the 240x320 splash/logo images after the shared 480x800 ones.

    Each source must be a regular file, the expected format, exactly 240x320 and match its pinned
    hash, so a wrong-sized image can never reach the V1 panel."""
    installed = {}
    for rel, (kind, asset) in V1_BOOT_ARTWORK.items():
        source = ASSET_REPO / asset
        safe_regular(source, "V1 boot artwork")
        data = source.read_bytes()
        info = image_format_and_size(data)
        if info is None or info[0] != kind or (info[1], info[2]) != V1_PANEL:
            raise RepackError(f"V1 boot image must be {kind} {V1_PANEL[0]}x{V1_PANEL[1]}: {asset} (found {info})")
        if hashlib.sha256(data).hexdigest() != V1_BOOT_ARTWORK_SHA256[kind]:
            raise RepackError("V1 boot image differs from its pinned hash: " + asset)
        target = root / rel
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RepackError("unsafe V1 boot image destination: " + rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(target) != V1_BOOT_ARTWORK_SHA256[kind]:
            raise RepackError("installed V1 boot image failed its hash check: " + rel)
        installed[rel] = {"sha256": V1_BOOT_ARTWORK_SHA256[kind], "format": kind, "size": f"{V1_PANEL[0]}x{V1_PANEL[1]}"}
    return installed


def install_speex_runtime(source: pathlib.Path, root: pathlib.Path) -> dict[str, object]:
    files = ("usr/lib/libspeexdsp.so.1.5.2",
             "usr/lib/alsa-lib/libasound_module_rate_speexrate.so")
    aliases = {
        "usr/lib/libspeexdsp.so.1": "libspeexdsp.so.1.5.2",
        "usr/lib/alsa-lib/libasound_module_rate_speexrate_best.so": "libasound_module_rate_speexrate.so",
        "usr/lib/alsa-lib/libasound_module_rate_speexrate_medium.so": "libasound_module_rate_speexrate.so",
    }
    for rel in (*files, *aliases):
        if (root / rel).exists() or (root / rel).is_symlink():
            raise RepackError("unexpected pre-existing Speex runtime: " + rel)
    for rel in files:
        safe_regular(source / rel, "approved Speex runtime")
        check_elf_compatibility(source / rel, root, {"libspeexdsp.so.1"})
    result = {rel: copy_explicit_file(source / rel, root / rel, "Speex runtime") for rel in files}
    for rel, target in aliases.items():
        (root / rel).symlink_to(target)
        result[rel] = {"symlink": target}
    return result


def install_ssc_runtime(r1_root: pathlib.Path, v1_root: pathlib.Path) -> dict[str, object]:
    # Prove V1's active stock boot script is the exact revision we reviewed.
    scripts = v1_root / "usr/bin"
    bt_init = scripts / "bt_init"
    if not bt_init.is_file() or bt_init.is_symlink():
        raise RepackError("V1 stock bt_init is missing or linked")
    init_text = bt_init.read_text()
    patched_init = patch_bt_init_text(init_text)
    bt_resume = scripts / "bt_resume"
    if not bt_resume.is_file() or bt_resume.is_symlink():
        raise RepackError("V1 stock bt_resume is missing or linked")
    text = bt_resume.read_text()
    patched = patch_bt_resume_text(text)

    required = [r1_root / rel for rel in RUNTIME_FILES]
    for p in required:
        safe_regular(p, "approved R1 BlueALSA runtime")
    if digest(r1_root / "usr/bin/bluealsad") != SSC_DAEMON_SHA256:
        raise RepackError("R1 bluealsad is not the pinned static-SSC daemon")
    # All runtime ELF files must use the V1 loader and have their direct
    # dependencies in stock V1 or this explicit candidate payload.
    supplied_sonames = {"libopenaptx.so.0"}
    for p in required:
        check_elf_compatibility(p, v1_root, supplied_sonames)
    lib_source = r1_root / "usr/lib/libopenaptx.so.0.2.0"
    safe_regular(lib_source, "approved R1 OpenAPTX runtime library")
    check_elf_compatibility(lib_source, v1_root, set())
    lib_temp = v1_root / "usr/lib/libopenaptx.so.0.2.0"
    lib_link = v1_root / "usr/lib/libopenaptx.so.0"
    if lib_temp.exists() or lib_link.exists() or lib_temp.is_symlink() or lib_link.is_symlink():
        raise RepackError("V1 stock already has one of the required libopenaptx.so.0 paths")
    copied = {}
    for src in required:
        rel = src.relative_to(r1_root)
        dest = v1_root / rel
        if "libasound_module_" in src.name:
            # Keep exact OEM modules for the documented manual rollback.
            backup = v1_root / "usr/lib/alsa-lib/stock-v1" / src.name
            if not dest.is_file() or dest.is_symlink() or backup.exists():
                raise RepackError(f"expected regular OEM ALSA module or empty backup path: {dest}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, backup)
            dest.unlink()
        copied[src.name] = copy_explicit_file(src, dest, "approved R1 runtime")
    copied[lib_source.name] = copy_explicit_file(lib_source, lib_temp, "approved R1 OpenAPTX library")
    lib_link.symlink_to(lib_temp.name)
    library_overlay = install_runtime_library_overlay(r1_root, v1_root)

    backup = scripts / "bt_resume.oem"
    init_backup = scripts / "bt_init.oem"
    if backup.exists() or backup.is_symlink() or init_backup.exists() or init_backup.is_symlink():
        raise RepackError("bt_init.oem/bt_resume.oem restore path already exists")
    old_init = bt_init.read_bytes()
    shutil.copy2(bt_init, init_backup)
    bt_init.write_bytes(patched_init.encode("utf-8"))
    bt_init.chmod(bt_init.stat().st_mode | 0o111)
    run(["sh", "-n", str(bt_init)])

    old = bt_resume.read_bytes()
    new = patched.encode()
    shutil.copy2(bt_resume, backup)
    bt_resume.write_bytes(new)
    bt_resume.chmod(bt_resume.stat().st_mode | 0o111)
    run(["sh", "-n", str(bt_resume)])
    return {
        "runtime_files": copied,
        "glib_runtime_overlay": library_overlay,
        "bt_init": {"original_sha256": hashlib.sha256(old_init).hexdigest(), "patched_sha256": digest(bt_init), "oem_backup": str(init_backup)},
        "bt_resume": {"original_sha256": hashlib.sha256(old).hexdigest(), "patched_sha256": digest(bt_resume), "oem_backup": str(backup)},
        "oem_alsa_module_backup_dir": "/usr/lib/alsa-lib/stock-v1",
        "ssc_static_in_daemon": "libssc.so.0" not in run(["readelf", "-d", str(v1_root / "usr/bin/bluealsad")], capture=True).stdout,
    }


def install_bluez_stack(r1_root: pathlib.Path, v1_root: pathlib.Path) -> dict[str, object]:
    """Bring V1 onto the BlueZ 5.87 set of the R1 base, keeping TempoTec's bt_init radio bring-up."""
    pins = {}
    for line in OVERLAY_PINS_FILE.read_text().splitlines():
        if line.strip():
            value, rel = line.split()
            pins[rel] = value
    expected = {rel: pins[rel] for rel in BLUEZ_OVERLAY_FILES}
    expected.update(BLUEZ_BASE_SHA256)
    replaced: dict[str, object] = {}
    for rel, want in expected.items():
        src = r1_root / rel
        safe_regular(src, "approved R1 BlueZ file")
        if digest(src) != want:
            raise RepackError("R1 BlueZ file is not the pinned one: " + rel)
        if rel in BLUEZ_ELF_FILES:
            check_elf_compatibility(src, v1_root, {"libbluetooth.so.3"})
        dest = v1_root / rel
        if rel.endswith("libbluetooth.so.3.19.16"):
            if dest.exists() or dest.is_symlink():
                raise RepackError("V1 stock already has libbluetooth 3.19.16")
        else:
            safe_regular(dest, "stock V1 BlueZ file")
            dest.unlink()
        replaced[rel] = copy_explicit_file(src, dest, "approved R1 BlueZ file")
    check_elf_compatibility(r1_root / "usr/lib/libbluetooth.so.3.19.16", v1_root, set())
    conf_src = r1_root / "etc/bluetooth/main.conf"
    safe_regular(conf_src, "approved R1 BlueZ configuration")
    conf = v1_root / "etc/bluetooth/main.conf"
    safe_regular(conf, "stock V1 BlueZ configuration")
    conf.write_bytes(v1_main_conf(conf_src.read_bytes()))
    replaced["etc/bluetooth/main.conf"] = {"path": str(conf), "sha256": digest(conf)}
    for rel, old_target in OLD_V1_LIBBLUETOOTH_LINKS.items():
        link = v1_root / rel
        if not link.is_symlink() or os.readlink(link) != old_target:
            raise RepackError("unexpected stock V1 libbluetooth link: " + rel)
    for rel, target in NEW_LIBBLUETOOTH_LINKS.items():
        link = v1_root / rel
        link.unlink()
        link.symlink_to(target)
    tracked: dict[str, object] = {}
    for rel in BLUEZ_TRACKED_FILES:
        src = ASSET_REPO / "firmware/overlay" / rel
        dest = v1_root / rel
        tracked[rel] = copy_explicit_file(src, dest, "tracked BlueZ support file")
        dest.chmod(src.stat().st_mode & 0o777)
    run(["sh", "-n", str(v1_root / "etc/init.d/S81compas_obex")])
    return {"replaced": replaced, "tracked": tracked, "libbluetooth_links": NEW_LIBBLUETOOTH_LINKS}


def v1_main_conf(r1_conf: bytes) -> bytes:
    """The R1 main.conf with V1's own DiscoverableTimeout."""
    if hashlib.sha256(r1_conf).hexdigest() != R1_MAIN_CONF_SHA256:
        raise RepackError("R1 main.conf is not the pinned one")
    text = r1_conf.decode("utf-8")
    old = "DiscoverableTimeout = 180\n"
    if text.count(old) != 1 or "BroadcomHighPriority = true\n" not in text:
        raise RepackError("R1 main.conf lacks the expected DiscoverableTimeout / BroadcomHighPriority lines")
    new = "DiscoverableTimeout = 0\n"
    out = text.replace(old, new, 1).encode("utf-8")
    if hashlib.sha256(out).hexdigest() != V1_MAIN_CONF_SHA256:
        raise RepackError("generated V1 main.conf differs from its pin")
    return out


def bluez_changed_paths() -> list[str]:
    paths = ["etc/bluetooth/main.conf", *BLUEZ_OVERLAY_FILES, *BLUEZ_BASE_SHA256, *NEW_LIBBLUETOOTH_LINKS, *BLUEZ_TRACKED_FILES]
    parents = {str(parent) for rel in paths for parent in pathlib.PurePosixPath(rel).parents if str(parent) != "."}
    return sorted({*paths, *parents})


def update_sidecar(template: pathlib.Path, output: pathlib.Path, md5_hex: str) -> None:
    safe_regular(template, "official V1 MD5 sidecar")
    text = template.read_text()
    if not re.search(r"(?i)\b[0-9a-f]{32}\b", text):
        raise RepackError("official sidecar lacks a 32-digit MD5 value")
    text = re.sub(r"(?i)\b[0-9a-f]{32}\b", md5_hex, text, count=1)
    if "v1.upt" not in text:
        raise RepackError("official sidecar does not name v1.upt")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)


def repack(base: pathlib.Path, player: pathlib.Path, r1_candidate: pathlib.Path, output: pathlib.Path,
           sidecar_template: pathlib.Path, sidecar_output: pathlib.Path, manifest_path: pathlib.Path,
           tmp_parent: pathlib.Path) -> dict[str, object]:
    for cmd in ("7z", "unsquashfs", "mksquashfs", "genisoimage", "readelf", "sha256sum"):
        if shutil.which(cmd) is None:
            raise RepackError(f"missing required host tool: {cmd}")
    if digest(base) != BASE_SHA256 or digest(base, "md5") != BASE_MD5:
        raise RepackError("base UPT does not match the verified official TempoTec V1 1.2 image")
    player_info = validate_player(player)
    r1_candidate_sha256 = digest(r1_candidate)
    if r1_candidate_sha256 != R1_SSC_UPT_SHA256:
        # Any R1 image built by repack_upt.sh with the pinned SSC overlay is
        # accepted: the BlueALSA daemon and every library copied from it are
        # hash-pinned individually below (SSC_DAEMON_SHA256, RUNTIME_LIBRARY_SHA256).
        print("note: R1 source is not the original QA image " + R1_SSC_UPT_SHA256[:12] +
              "; relying on per-file runtime pins", file=sys.stderr)
    if (base.resolve() == output.resolve() or sidecar_template.resolve() == sidecar_output.resolve() or
            output.exists() or sidecar_output.exists() or manifest_path.exists()):
        raise RepackError("output path must be new and differ from the official base")

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v1-repack-", dir=tmp_parent) as td:
        work = pathlib.Path(td)
        validate_upt_archive(base)
        ota, rootfs, base_images = extract_rootfs(base, work / "base")
        # Validate base image payload is the official kernel and V1 layout.
        if base_images["xImage"]["sha256"] != BASE_KERNEL_SHA256:
            raise RepackError("base kernel hash differs from verified official V1 kernel")
        v1_root = work / "v1-root"
        run(["unsquashfs", "-no-xattrs", "-d", str(v1_root), str(rootfs)])
        device, dimensions = board_from_config(v1_root / "usr/resource/config.json")
        stock_inventory = tree_inventory(v1_root)
        required_launch = v1_root / "usr/bin/hiby_player"
        required_wrapper = v1_root / "usr/bin/hiby_player.sh"
        init_script = v1_root / "etc/init.d/S92_03_start_music_player"
        if not required_launch.is_file() or required_launch.is_symlink() or not required_wrapper.is_file() or required_wrapper.is_symlink():
            raise RepackError("V1 stock player or launcher path is missing/unsafe")
        if not init_script.is_file() or init_script.is_symlink():
            raise RepackError("V1 stock S92 launcher is missing or linked")
        stock_init_hash = digest(init_script)

        r1_work = work / "r1"
        validate_upt_archive(r1_candidate)
        _, r1_rootfs, r1_images = extract_rootfs(r1_candidate, r1_work)
        r1_root = work / "r1-root"
        run(["unsquashfs", "-no-xattrs", "-d", str(r1_root), str(r1_rootfs)])

        assets = copy_theme_and_fonts(r1_root, v1_root)
        runtime = install_ssc_runtime(r1_root, v1_root)
        speex_runtime = install_speex_runtime(r1_root, v1_root)
        bluez_stack = install_bluez_stack(r1_root, v1_root)

        # Preserve OEM executable and wrapper byte-for-byte, then change only
        # the single active command in the original launcher.
        oem_player = v1_root / "usr/bin/hiby_player.oem"
        if oem_player.exists() or oem_player.is_symlink():
            raise RepackError("OEM player restore path already exists")
        shutil.copy2(required_launch, oem_player)
        required_launch.unlink()
        compas_path = v1_root / "usr/bin/compas_player"
        shutil.copy2(player, compas_path)
        compas_path.chmod(0o755)
        launcher_backup = v1_root / "usr/bin/hiby_player.sh.oem"
        launcher_delta = replace_script(required_wrapper, launcher_backup, patch_launcher_text)
        init_hash_after = digest(init_script)
        if init_hash_after != stock_init_hash:
            raise RepackError("stock boot init script changed unexpectedly")
        removed_oem_files = remove_unused_oem_files(v1_root)
        current_assets = copy_current_assets(v1_root)
        clean_os = clean_new_os(v1_root)
        current_assets.update(install_required_usb_overlay(v1_root))
        current_assets.update(install_v1_boot_artwork(v1_root))
        clean_paths = [item["path"].lstrip("/") for item in clean_os["removed"] + clean_os["naming_updates"]]
        allowed_paths = list(current_assets) + clean_paths + bluez_changed_paths()
        changed_paths = verify_only_allowed_changes(stock_inventory, tree_inventory(v1_root), allowed_paths)

        # Rebuild only the compressed rootfs. Keep xImage and all other outer
        # ISO files/chunks byte-for-byte; create new rootfs OTA chains.
        rebuilt = work / "new-rootfs.squashfs"
        run(["mksquashfs", str(v1_root), str(rebuilt), "-comp", "lzo", "-b", "131072", "-all-root", "-noappend", "-no-xattrs"])
        new_md5 = digest(rebuilt, "md5")
        new_size = rebuilt.stat().st_size
        if new_size > base_images["rootfs.squashfs"]["size_bytes"]:
            raise RepackError("V1 rootfs exceeds the verified stock rootfs size")

        # Rewrite ota_update.in in the compact layout repack_upt.sh writes (no blank lines): the
        # player's own parser (firmware_image.c parse_manifest) rejects the stock TempoTec
        # layout. Only the rootfs size and MD5 change; kernel values come from the base.
        k = base_images["xImage"]
        metadata_text = (
            "ota_version=0\n"
            f"img_type=kernel\nimg_name=xImage\nimg_size={k['size_bytes']}\nimg_md5={k['md5']}\n"
            f"img_type=rootfs\nimg_name=rootfs.squashfs\nimg_size={new_size}\nimg_md5={new_md5}\n"
        )
        (ota / "ota_update.in").write_text(metadata_text)

        for p in ota.glob("rootfs.squashfs.[0-9][0-9][0-9][0-9].*"):
            p.unlink()
        for p in ota.glob("ota_md5_rootfs.squashfs.*"):
            p.unlink()
        chunk_chain = []
        previous = new_md5
        chain_file = ota / f"ota_md5_rootfs.squashfs.{new_md5}"
        with rebuilt.open("rb") as source:
            index = 0
            while True:
                data = source.read(IMAGE_CHUNK_SIZE)
                if not data:
                    break
                part_md5 = hashlib.md5(data).hexdigest()
                name = f"rootfs.squashfs.{index:04d}.{previous}"
                (ota / name).write_bytes(data)
                chunk_chain.append(part_md5)
                previous = part_md5
                index += 1
        chain_file.write_text("".join(item + "\n" for item in chunk_chain))

        # Revalidate generated metadata and chunk chain before creating output.
        checked_rootfs = work / "verified-new-rootfs.squashfs"
        final_root_info = verify_image_chunks(ota, "rootfs", "rootfs.squashfs", checked_rootfs)
        if digest(checked_rootfs) != digest(rebuilt):
            raise RepackError("rebuilt rootfs differs after chunk reconstruction")
        verified_kernel = work / "verified-xImage"
        final_kernel_info = verify_image_chunks(ota, "kernel", "xImage", verified_kernel)
        if final_kernel_info["sha256"] != BASE_KERNEL_SHA256:
            raise RepackError("kernel changed while repacking")

        # Keep the vendor's ISO metadata and files; write a new UPT next to the
        # explicit candidate output. No init/recovery/kernel/module files are
        # removed or replaced.
        # Match the HiBy repacker and the published images: the marker file is empty
        # (the stock V1 file holds a single newline).
        (ota / "ota_v0.ok").write_bytes(b"")
        package_temp = work / "candidate-v1.upt"
        run(["genisoimage", "-o", str(package_temp), "-J", "-r", str(work / "base" / "outer")])
        run(["7z", "t", str(package_temp)])
        upt_md5 = digest(package_temp, "md5")
        sidecar_tmp = work / "v1_md5.txt"
        update_sidecar(sidecar_template, sidecar_tmp, upt_md5)

        # Ensure the rebuilt output contains no unexpected stock core changes.
        _, check_rootfs, result_images = extract_rootfs(package_temp, work / "verify-output")
        result_root = work / "verify-root"
        run(["unsquashfs", "-no-xattrs", "-d", str(result_root), str(check_rootfs)])
        if digest(result_root / "etc/init.d/S92_03_start_music_player") != stock_init_hash:
            raise RepackError("final image does not preserve the stock V1 boot-init script")
        for rel in removed_oem_files:
            if rel not in current_assets and (result_root / rel).exists():
                raise RepackError("unused OEM file remains in final image: " + rel)
        for rel, record in current_assets.items():
            asset = result_root / rel
            if "symlink" in record:
                if not asset.is_symlink() or os.readlink(asset) != record["symlink"]:
                    raise RepackError("final tracked asset alias mismatch: " + rel)
            elif not asset.is_file() or digest(asset) != record["sha256"]:
                raise RepackError("final tracked asset hash mismatch: " + rel)
        final_changed_paths = verify_only_allowed_changes(stock_inventory, tree_inventory(result_root), allowed_paths)
        if final_changed_paths != changed_paths:
            raise RepackError("final rootfs delta differs from the explicitly prepared file delta")
        final_runtime_closure = check_runtime_strong_symbol_closure(
            result_root, (*RUNTIME_FILES, *RUNTIME_LIBRARY_FILES, *BLUEZ_ELF_FILES)
        )
        if not final_runtime_closure["closed"]:
            sample = final_runtime_closure["unresolved_strong_symbols"][:8] or final_runtime_closure["unresolved_libraries"][:8]
            raise RepackError("final V1 UPT runtime has unresolved strong ELF imports: " + repr(sample))
        for name in ("hiby_player.sh", "bt_init", "bt_resume"):
            if digest(result_root / "usr/bin" / name) != digest(v1_root / "usr/bin" / name):
                raise RepackError("final active launcher/Bluetooth helper differs: " + name)
        if list((result_root / "usr/bin").glob("*.oem")) or (result_root / "usr/lib/alsa-lib/stock-v1").exists():
            raise RepackError("old OS backups remain in the final image")
        if digest(result_root / "usr/bin/compas_player") != player_info["sha256"]:
            raise RepackError("final image player hash differs from the marked input")

        if package_temp.stat().st_size > base.stat().st_size:
            raise RepackError("V1 UPT exceeds the verified official image size")
        shutil.copy2(package_temp, output)
        sidecar_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sidecar_tmp, sidecar_output)
        result = {
            "schema_version": 1,
            "experimental": True,
            "hardware_validation": "UNVERIFIED: host-only package preparation; no device test or flash",
            "board": device,
            "screen": {"width": dimensions[0], "height": dimensions[1]},
            "base_upt": {"sha256": BASE_SHA256, "md5": BASE_MD5, "size_bytes": base.stat().st_size},
            "player": player_info,
            "approved_r1_source_upt_sha256": r1_candidate_sha256,
            "base_components": base_images,
            "r1_source_components": r1_images,
            "candidate_components": {"xImage": final_kernel_info, "rootfs.squashfs": final_root_info},
            "upt": {"path": str(output), "sha256": digest(output), "md5": upt_md5, "size_bytes": output.stat().st_size},
            "md5_sidecar": {"path": str(sidecar_output), "sha256": digest(sidecar_output)},
            "clean_os": clean_os,
            "assets": assets,
            "current_tracked_assets": current_assets,
            "bluealsa_ssc_runtime": runtime,
            "bluealsa_runtime_final_strong_symbol_closure": final_runtime_closure,
            "speex_runtime": speex_runtime,
            "bluez_stack": bluez_stack,
            "recovery": "Use the official TempoTec recovery firmware; no old OS backup payload is shipped.",
            "limit_status": "Conservative gate: rootfs and whole UPT are no larger than the verified official stock image. Exact partition map and device validation remain unavailable.",
            "removed_unused_oem_files": removed_oem_files,
            "changed_rootfs_paths": changed_paths,
            "userdata_payload": False,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, indent=2) + "\n")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=pathlib.Path, required=True, help="verified official publicv1.upt")
    parser.add_argument("--player", type=pathlib.Path, required=True, help="static, V1-marked Compas MIPS32r2 player")
    parser.add_argument("--r1-candidate", type=pathlib.Path, required=True, help="verified R1 static-SSC QA UPT (resources/runtime source)")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="new v1.upt output path")
    parser.add_argument("--md5-output", type=pathlib.Path, required=True, help="v1_md5.txt output path")
    parser.add_argument("--manifest", type=pathlib.Path, required=True, help="JSON evidence manifest output")
    parser.add_argument("--tmp", type=pathlib.Path, required=True, help="cache-owned temp directory")
    parser.add_argument("--md5-template", type=pathlib.Path, default=None,
                        help="v1_md5.txt format template (default: v1_md5.txt next to --base; "
                             "firmware/v1/v1_md5.template.txt is tracked)")
    args = parser.parse_args()
    base_dir = args.base.resolve().parent
    try:
        result = repack(args.base.resolve(), args.player.resolve(), args.r1_candidate.resolve(),
                        args.output.resolve(), (args.md5_template or base_dir / "v1_md5.txt").resolve(), args.md5_output.resolve(),
                        args.manifest.resolve(), args.tmp.resolve())
    except RepackError as exc:
        print(f"V1 repack rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"upt": result["upt"], "md5_sidecar": result["md5_sidecar"], "experimental": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
