#!/usr/bin/env python3
"""Replace only the player in the pinned V1 release UPT (host-only).

Used for the v1.3.0 V1 image: the base is the V1 image produced by
repack_v1_upt.py (BASE_SHA256 below), the output differs from it only in
usr/bin/compas_player. Set V1_BASE_UPT to that base, SQUASHFS_TOOLS to a
squashfs-tools 4.6.1 build directory whose unsquashfs prints xattrs NUL
terminated (see docs/v1.md), and V1_MD5_TEMPLATE to a v1_md5.txt template.

The stock SquashFS pseudo manifest is used to preserve numeric owners, modes,
timestamps, links and every xattr without requiring host SELinux privileges.
The helper unsquashfs is the diagnostics-local 4.6.1 build with the reviewed
NUL-terminated xattr formatting fix; no firmware source is changed here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


BASE_SHA256 = "131b81cb23738964d135064eca694f7ac10637712740cc685805321a07d7cc37"
BASE_MD5 = "4ec1e87b95c086bf0e34ed9e6a43e4c1"
BASE_KERNEL_SHA256 = "3a83176b9d8da6c09eedd64348ea8a612ad5ee2ae532ce04ccadd7d0fa4bb25d"
BASE_PLAYER_SHA256 = "16cab1ced9293ddd056cacd355ba78033e2f8642b43d91217237349608e35003"
EXPECTED_PLAYER_SHA256 = "f14345d65efbc545168a2ddbc5c739c614436e55b4ee505e7214fcd36387ad31"
# Container ceilings from this hash-pinned official vendor stock V1 UPT; SHA-256 9f929a92319a05a81bbd16cbf0fb8a886a9bb2def192f5a6786b6ea7032fa05d.
STOCK_BUDGET_SOURCE_SHA256 = "9f929a92319a05a81bbd16cbf0fb8a886a9bb2def192f5a6786b6ea7032fa05d"
STOCK_ROOTFS_BUDGET = 35_762_176
STOCK_UPT_BUDGET = 39_907_328
PLAYER_REL = "usr/bin/compas_player"
PSEUDO_DATA_MARKER = b"# START OF DATA - DO NOT MODIFY"
IMAGE_CHUNK_SIZE = 512 * 1024

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = pathlib.Path(os.environ.get("SQUASHFS_TOOLS", "/usr/bin"))
UNSQUASHFS = TOOLS / "unsquashfs"
MKSQUASHFS = TOOLS / "mksquashfs"
BASE = pathlib.Path(os.environ.get("V1_BASE_UPT", "v1-base.upt"))
SIDECAR = pathlib.Path(os.environ.get("V1_MD5_TEMPLATE", str(BASE.parent / "v1_md5.txt")))
HELPER_PATH = HERE / "repack_v1_upt.py"


class RepackError(RuntimeError):
    pass


def load_audited_helper():
    spec = importlib.util.spec_from_file_location("audited_v1_repack_primitives", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RepackError(f"cannot load audited V1 helper: {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: pathlib.Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(item) for item in argv], check=True, text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RepackError(f"command failed ({exc.returncode}): {argv[0]}" + (f": {detail[-500:]}" if detail else "")) from exc


def pseudo_dump(squashfs: pathlib.Path, output: pathlib.Path) -> bytes:
    run([UNSQUASHFS, "-pf", output, squashfs])
    raw = output.read_bytes()
    if PSEUDO_DATA_MARKER not in raw:
        raise RepackError("SquashFS pseudo manifest lacks its binary data section")
    return raw


def pseudo_header(raw: bytes) -> bytes:
    return raw.split(PSEUDO_DATA_MARKER, 1)[0]


def pseudo_records(header: bytes) -> dict[str, list[str]]:
    try:
        lines = header.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RepackError("SquashFS pseudo header is not UTF-8") from exc
    records: dict[str, list[str]] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if " x " in line:
            path = shlex.split(line.split(" x ", 1)[0], comments=False)[0]
        else:
            fields = shlex.split(line, comments=False)
            if len(fields) < 2:
                raise RepackError(f"unparseable SquashFS pseudo record: {line!r}")
            path = fields[0]
        records.setdefault(path, []).append(line)
    return records


def normalize_pseudo(header: bytes, *, changed_player: bool) -> dict[str, tuple[str, ...]]:
    records = pseudo_records(header)
    normalized: dict[str, tuple[str, ...]] = {}
    for path, lines in records.items():
        cooked = []
        for line in lines:
            if " x " in line:
                cooked.append(line)
                continue
            fields = shlex.split(line, comments=False)
            if len(fields) >= 2 and fields[0] == PLAYER_REL and changed_player and fields[1] == "R":
                if len(fields) != 9:
                    raise RepackError("unexpected player pseudo record format")
                # Keep type, timestamp, mode, uid, gid and sparse semantics.
                # Length/offset necessarily change when replacing file bytes.
                cooked.append(" ".join(fields[:6] + ["<player-size>", "<player-data-offset>", fields[8]]))
            elif len(fields) == 9 and fields[1] == "R":
                # Payload offsets can move as the SquashFS data stream is
                # rebuilt; payload sizes and sparse semantics must remain.
                cooked.append(" ".join(fields[:7] + ["<data-offset>", fields[8]]))
            else:
                cooked.append(line)
        normalized[path] = tuple(cooked)
    return normalized


def tree_state(root: pathlib.Path) -> dict[str, tuple[object, ...]]:
    """Capture tree payload, Unix modes and hard-link groups (xattrs live in pseudo)."""
    out: dict[str, tuple[object, ...]] = {}
    inode_groups: dict[tuple[int, int], list[str]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        if path.is_symlink():
            out[rel] = ("symlink", st.st_mode & 0o7777, os.readlink(path), st.st_mtime_ns)
        elif path.is_dir():
            out[rel] = ("directory", st.st_mode & 0o7777, st.st_mtime_ns)
        elif path.is_file():
            out[rel] = ("file", st.st_mode & 0o7777, digest(path), st.st_mtime_ns)
            if st.st_nlink > 1:
                inode_groups.setdefault((st.st_dev, st.st_ino), []).append(rel)
        else:
            out[rel] = ("other", st.st_mode & 0o7777, st.st_rdev, st.st_mtime_ns)
    # Include only multi-path hard-link equivalence classes, not host inode IDs.
    for members in inode_groups.values():
        if len(members) > 1:
            for rel in members:
                out[rel] = (*out[rel], tuple(members))
    return out


def regular_file_manifest(root: pathlib.Path) -> dict[str, tuple[int, str]]:
    manifest = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RepackError(f"unexpected symlink in extracted UPT: {path.relative_to(root)}")
        if path.is_file():
            manifest[path.relative_to(root).as_posix()] = (path.stat().st_size, digest(path))
    return manifest


def rewrite_player_record(pseudo: pathlib.Path, player_source: pathlib.Path) -> None:
    raw = pseudo.read_bytes()
    marker_at = raw.find(PSEUDO_DATA_MARKER)
    if marker_at < 0:
        raise RepackError("missing pseudo data marker before player edit")
    header, data = raw[:marker_at], raw[marker_at:]
    text = header.decode("utf-8")
    pattern = re.compile(r"(?m)^usr/bin/compas_player R (\d+) ([0-7]+) (\d+) (\d+) (\d+) (\d+) (\d+)$")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RepackError("pinned V1 rootfs must contain exactly one regular compas_player pseudo record")
    match = matches[0]
    ts, mode, uid, gid = match.group(1, 2, 3, 4)
    command = "cat " + shlex.quote(str(player_source.resolve()))
    replacement = f"usr/bin/compas_player F {ts} {mode} {uid} {gid} {command}"
    text = text[:match.start()] + replacement + text[match.end():]
    pseudo.write_bytes(text.encode("utf-8") + data)


def update_sidecar(template: pathlib.Path, output: pathlib.Path, md5_hex: str) -> None:
    safe = template.is_file() and not template.is_symlink()
    if not safe:
        raise RepackError("official v1_md5.txt sidecar is missing or unsafe")
    text = template.read_text()
    if not re.search(r"(?i)\b[0-9a-f]{32}\b", text) or "v1.upt" not in text:
        raise RepackError("official sidecar format lacks its MD5 value or v1.upt name")
    output.write_text(re.sub(r"(?i)\b[0-9a-f]{32}\b", md5_hex, text, count=1))


def repack(player: pathlib.Path, output: pathlib.Path, sidecar_output: pathlib.Path,
           manifest_path: pathlib.Path, tmp_parent: pathlib.Path) -> dict[str, object]:
    helper = load_audited_helper()
    for tool in (UNSQUASHFS, MKSQUASHFS):
        if not tool.is_file():
            raise RepackError(f"missing reviewed local SquashFS tool: {tool}")
    for cmd in ("7z", "genisoimage", "readelf"):
        if shutil.which(cmd) is None:
            raise RepackError(f"missing required host tool: {cmd}")
    if digest(BASE) != BASE_SHA256 or digest(BASE, "md5") != BASE_MD5:
        raise RepackError("base UPT does not match the pinned released V1 asset")
    player_info = helper.validate_player(player)
    if player_info["sha256"] != EXPECTED_PLAYER_SHA256:
        raise RepackError("replacement player is not the independently verified isolated V1 build")
    if output.exists() or output.is_symlink() or sidecar_output.exists() or sidecar_output.is_symlink() or manifest_path.exists():
        raise RepackError("all output paths must be new; refusing to overwrite evidence or release files")
    if output.resolve() == BASE.resolve() or sidecar_output.resolve() == SIDECAR.resolve():
        raise RepackError("output paths must not alias the official base assets")

    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v1-player-only-", dir=tmp_parent) as td:
        work = pathlib.Path(td)
        helper.validate_upt_archive(BASE)
        unpack = work / "outer"
        unpack.mkdir()
        run(["7z", "x", "-y", "-o" + str(unpack), BASE])
        original_outer_manifest = regular_file_manifest(unpack)
        ota = unpack / "ota_v0"
        if not (ota / "ota_v0.ok").is_file():
            raise RepackError("pinned V1 UPT lacks ota_v0.ok")
        images = helper.parse_ota_metadata(ota / "ota_update.in")
        if set(images) != {"kernel", "rootfs"}:
            raise RepackError("pinned V1 UPT must have exactly kernel and rootfs components")
        original_kernel = work / "original-xImage"
        original_rootfs = work / "original-rootfs.squashfs"
        source_kernel = helper.verify_image_chunks(ota, "kernel", "xImage", original_kernel)
        source_rootfs = helper.verify_image_chunks(ota, "rootfs", "rootfs.squashfs", original_rootfs)
        if source_kernel["sha256"] != BASE_KERNEL_SHA256:
            raise RepackError("V1 kernel differs from the pinned released kernel")

        original_pseudo_file = work / "original-rootfs.pseudo"
        original_pseudo = pseudo_dump(original_rootfs, original_pseudo_file)
        original_header = pseudo_header(original_pseudo)
        original_records = pseudo_records(original_header)
        player_record = original_records.get(PLAYER_REL)
        if not player_record or not any(line.startswith(PLAYER_REL + " R ") for line in player_record):
            raise RepackError("pinned rootfs player pseudo metadata is missing or not a regular file")

        root = work / "root"
        run([UNSQUASHFS, "-no-xattrs", "-d", root, original_rootfs])
        device, dimensions = helper.board_from_config(root / "usr/resource/config.json")
        player_dest = root / PLAYER_REL
        if device != "V1" or dimensions != (240, 320):
            raise RepackError(f"base configuration is not TempoTec V1 240x320: {device}/{dimensions}")
        if not player_dest.is_file() or player_dest.is_symlink() or player_dest.stat().st_nlink != 1:
            raise RepackError("existing compas_player must be a plain, non-hardlinked regular file")
        if digest(player_dest) != BASE_PLAYER_SHA256:
            raise RepackError("embedded baseline player SHA differs from the audited released V1 player")
        before = tree_state(root)
        # Retain tree-side mode/time while pseudo definitions restore original
        # numeric ownership and xattrs into the rebuilt SquashFS image.
        original_stat = player_dest.stat()
        shutil.copyfile(player, player_dest)
        player_dest.chmod(original_stat.st_mode & 0o7777)
        os.utime(player_dest, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        after = tree_state(root)
        unexpected = [p for p in before.keys() | after.keys()
                      if p != PLAYER_REL and before.get(p) != after.get(p)]
        if unexpected:
            raise RepackError("root tree changed outside compas_player: " + ", ".join(unexpected[:10]))
        if before.get(PLAYER_REL, (None,))[0] != "file" or after.get(PLAYER_REL, (None,))[0] != "file":
            raise RepackError("compas_player file type changed")

        edited_pseudo_file = work / "edited-rootfs.pseudo"
        shutil.copyfile(original_pseudo_file, edited_pseudo_file)
        rewrite_player_record(edited_pseudo_file, player)
        rebuilt_rootfs = work / "rootfs.squashfs"
        run([MKSQUASHFS, root, rebuilt_rootfs, "-noappend", "-comp", "lzo", "-b", "131072",
             "-all-root", "-pseudo-override", "-pf", edited_pseudo_file,
             "-xattrs-include", r"^user\."])
        if rebuilt_rootfs.stat().st_size > STOCK_ROOTFS_BUDGET:
            raise RepackError("rebuilt rootfs exceeds the hash-pinned official V1 stock budget")

        rebuilt_pseudo_file = work / "rebuilt-rootfs.pseudo"
        rebuilt_pseudo = pseudo_dump(rebuilt_rootfs, rebuilt_pseudo_file)
        original_norm = normalize_pseudo(original_header, changed_player=True)
        rebuilt_norm = normalize_pseudo(pseudo_header(rebuilt_pseudo), changed_player=True)
        if original_norm != rebuilt_norm:
            paths = sorted(k for k in original_norm.keys() | rebuilt_norm.keys() if original_norm.get(k) != rebuilt_norm.get(k))
            sample = paths[0] if paths else "<unknown>"
            raise RepackError("SquashFS metadata/xattr/link manifest differs outside player data: " +
                              ", ".join(paths[:10]) + f"; {sample} original={original_norm.get(sample)!r} rebuilt={rebuilt_norm.get(sample)!r}")

        new_md5 = digest(rebuilt_rootfs, "md5")
        metadata = (ota / "ota_update.in").read_text()
        pattern = re.compile(r"(?ms)(img_type=rootfs\s*\nimg_name=rootfs\.squashfs\s*\nimg_size=)[0-9]+(\s*\nimg_md5=)[0-9a-fA-F]{32}")
        metadata, changed = pattern.subn(rf"\g<1>{rebuilt_rootfs.stat().st_size}\g<2>{new_md5}", metadata)
        if changed != 1:
            raise RepackError("could not safely update exactly the rootfs OTA metadata record")
        (ota / "ota_update.in").write_text(metadata)
        for chunk in ota.glob("rootfs.squashfs.[0-9][0-9][0-9][0-9].*"):
            chunk.unlink()
        for chain in ota.glob("ota_md5_rootfs.squashfs.*"):
            chain.unlink()
        chain = []
        previous = new_md5
        with rebuilt_rootfs.open("rb") as source:
            index = 0
            while data := source.read(IMAGE_CHUNK_SIZE):
                part_md5 = hashlib.md5(data).hexdigest()
                (ota / f"rootfs.squashfs.{index:04d}.{previous}").write_bytes(data)
                chain.append(part_md5)
                previous = part_md5
                index += 1
        (ota / f"ota_md5_rootfs.squashfs.{new_md5}").write_text("".join(item + "\n" for item in chain))

        check_rootfs = work / "verified-rootfs.squashfs"
        final_root_info = helper.verify_image_chunks(ota, "rootfs", "rootfs.squashfs", check_rootfs)
        if digest(check_rootfs) != digest(rebuilt_rootfs):
            raise RepackError("generated rootfs chunk chain does not reconstruct exact bytes")
        final_kernel = work / "verified-xImage"
        final_kernel_info = helper.verify_image_chunks(ota, "kernel", "xImage", final_kernel)
        if final_kernel_info["sha256"] != BASE_KERNEL_SHA256 or digest(final_kernel) != digest(original_kernel):
            raise RepackError("kernel component changed during repack")
        package_temp = work / "candidate-v1.upt"
        run(["genisoimage", "-o", package_temp, "-J", "-r", unpack])
        run(["7z", "t", package_temp])
        upt_md5 = digest(package_temp, "md5")
        sidecar_temp = work / "v1_md5.txt"
        update_sidecar(SIDECAR, sidecar_temp, upt_md5)
        if package_temp.stat().st_size > STOCK_UPT_BUDGET:
            raise RepackError("candidate UPT exceeds the hash-pinned official V1 stock budget")

        # Re-extract final package and verify only the intended component and
        # regenerated OTA records changed. The kernel's chunk set is byte-exact.
        final_unpack = work / "final-outer"
        final_unpack.mkdir()
        run(["7z", "x", "-y", "-o" + str(final_unpack), package_temp])
        final_ota = final_unpack / "ota_v0"
        final_outer_manifest = regular_file_manifest(final_unpack)
        final_metadata = helper.parse_ota_metadata(final_ota / "ota_update.in")
        if final_metadata.get("kernel") != images.get("kernel"):
            raise RepackError("kernel OTA metadata changed")
        expected_root_metadata = dict(images["rootfs"])
        expected_root_metadata["img_size"] = str(rebuilt_rootfs.stat().st_size)
        expected_root_metadata["img_md5"] = new_md5
        if final_metadata.get("rootfs") != expected_root_metadata:
            raise RepackError("rootfs OTA metadata changed outside its expected size/MD5 fields")
        allowed_outer_changes = {"ota_v0/ota_update.in"}
        allowed_outer_changes.update(p for p in original_outer_manifest if re.fullmatch(r"ota_v0/rootfs\.squashfs\.\d{4}\.[0-9a-f]{32}", p))
        allowed_outer_changes.update(p for p in original_outer_manifest if re.fullmatch(r"ota_v0/ota_md5_rootfs\.squashfs\.[0-9a-f]{32}", p))
        allowed_outer_changes.update(p for p in final_outer_manifest if re.fullmatch(r"ota_v0/rootfs\.squashfs\.\d{4}\.[0-9a-f]{32}", p))
        allowed_outer_changes.update(p for p in final_outer_manifest if re.fullmatch(r"ota_v0/ota_md5_rootfs\.squashfs\.[0-9a-f]{32}", p))
        outer_delta = {p for p in original_outer_manifest.keys() | final_outer_manifest.keys()
                       if original_outer_manifest.get(p) != final_outer_manifest.get(p)}
        unexpected_outer = sorted(outer_delta - allowed_outer_changes)
        if unexpected_outer:
            raise RepackError("UPT changed non-rootfs payloads: " + ", ".join(unexpected_outer[:10]))
        for original in ota.glob("xImage.[0-9][0-9][0-9][0-9].*"):
            counterpart = final_ota / original.name
            if not counterpart.is_file() or digest(original) != digest(counterpart):
                raise RepackError("non-root kernel chunk changed: " + original.name)
        final_root_file = work / "final-rootfs.squashfs"
        helper.verify_image_chunks(final_ota, "rootfs", "rootfs.squashfs", final_root_file)
        final_pseudo_file = work / "final-rootfs.pseudo"
        final_pseudo = pseudo_dump(final_root_file, final_pseudo_file)
        if normalize_pseudo(original_header, changed_player=True) != normalize_pseudo(pseudo_header(final_pseudo), changed_player=True):
            raise RepackError("final UPT rootfs metadata differs outside player data")
        final_tree = work / "final-tree"
        run([UNSQUASHFS, "-no-xattrs", "-d", final_tree, final_root_file])
        if digest(final_tree / PLAYER_REL) != player_info["sha256"]:
            raise RepackError("final UPT player bytes differ from validated input")
        final_state = tree_state(final_tree)
        expected_state = after
        changed_paths = sorted(p for p in expected_state.keys() | final_state.keys()
                               if p != PLAYER_REL and expected_state.get(p) != final_state.get(p))
        if changed_paths:
            raise RepackError("final extracted rootfs content/mode/link delta outside player: " + ", ".join(changed_paths[:10]))

        shutil.copy2(package_temp, output)
        shutil.copy2(sidecar_temp, sidecar_output)
        result = {
            "schema_version": 1,
            "hardware_validation": "UNVERIFIED: host-only package; not flashed",
            "board": device,
            "screen": {"width": dimensions[0], "height": dimensions[1]},
            "base_upt": {"sha256": BASE_SHA256, "md5": BASE_MD5, "size_bytes": BASE.stat().st_size},
            "base_player_sha256": BASE_PLAYER_SHA256,
            "published_input_budget": {
                "source": "official TempoTec V1 1.2 UPT (hash-pinned)",
                "source_sha256": STOCK_BUDGET_SOURCE_SHA256,
                "rootfs_bytes": STOCK_ROOTFS_BUDGET,
                "upt_bytes": STOCK_UPT_BUDGET,
            },
            "player": player_info,
            "base_components": {"xImage": source_kernel, "rootfs.squashfs": source_rootfs},
            "candidate_components": {"xImage": final_kernel_info, "rootfs.squashfs": final_root_info},
            "upt": {"path": str(output), "sha256": digest(output), "md5": upt_md5, "size_bytes": output.stat().st_size},
            "md5_sidecar": {"path": str(sidecar_output), "sha256": digest(sidecar_output)},
            "changed_rootfs_path": PLAYER_REL,
            "squashfs_metadata": "pseudo-manifest verified: numeric owner/mode/time, symlink/hardlink topology and all xattrs preserved outside player content",
            "recovery": "Pinned official V1 UPT is the rollback image.",
        }
        manifest_path.write_text(json.dumps(result, indent=2) + "\n")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", type=pathlib.Path, required=True, help="validated static V1 target player")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="new UPT output path")
    parser.add_argument("--md5-output", type=pathlib.Path, required=True, help="new v1_md5.txt output path")
    parser.add_argument("--manifest", type=pathlib.Path, required=True, help="new host evidence manifest path")
    parser.add_argument("--tmp", type=pathlib.Path, required=True, help="persistent host temporary workspace")
    args = parser.parse_args()
    try:
        result = repack(args.player.resolve(), args.output.resolve(), args.md5_output.resolve(),
                        args.manifest.resolve(), args.tmp.resolve())
    except RepackError as exc:
        print(f"V1 player-only repack rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"upt": result["upt"], "md5_sidecar": result["md5_sidecar"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
