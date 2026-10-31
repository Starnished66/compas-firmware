#!/usr/bin/env python3
"""Validate the V1 OTA kernel and optional zram overlay as a matched pair."""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import stat
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
HELPER = REPO / "scripts/firmware/package/repack_v1_upt.py"
OVERLAY = REPO / "firmware/overlay"
ZRAM_FILES = {
    "usr/bin/compas-zram": OVERLAY / "usr/bin/compas-zram",
    "etc/init.d/S31compas_zram": OVERLAY / "etc/init.d/S31compas_zram",
}
STOCK_KERNEL_SIZE = 3_731_520


def load_repacker():
    spec = importlib.util.spec_from_file_location("repack_v1_upt", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load V1 UPT validation helper: {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_zram_overlay(root: pathlib.Path, repack) -> bool:
    present = []
    for rel, source in ZRAM_FILES.items():
        target = root / rel
        for parent in target.parents:
            if parent.is_symlink():
                raise repack.RepackError(f"V1 zram overlay path traverses a symlink: {rel}")
            if parent == root:
                break
        exists = target.exists() or target.is_symlink()
        present.append(exists)
        if exists and (target.is_symlink() or not target.is_file()):
            raise repack.RepackError(f"V1 zram overlay path is not a regular file: {rel}")
    if any(present) and not all(present):
        raise repack.RepackError("V1 image contains only part of the two-file zram overlay")
    if not any(present):
        return False
    for rel, source in ZRAM_FILES.items():
        target = root / rel
        repack.safe_regular(source, "tracked V1 zram overlay source")
        if stat.S_IMODE(target.stat().st_mode) != 0o755:
            raise repack.RepackError(f"V1 zram overlay file must have mode 755: {rel}")
        if repack.digest(target) != repack.digest(source):
            raise repack.RepackError(f"V1 zram overlay file differs from tracked source: {rel}")
    return True


def validate_v1_image(ota: pathlib.Path, root: pathlib.Path, kernel_output: pathlib.Path,
                      repack=None) -> dict[str, object]:
    repack = repack or load_repacker()
    has_zram = validate_zram_overlay(root, repack)
    kernel_info = repack.verify_image_chunks(ota, "kernel", "xImage", kernel_output)
    if has_zram:
        pin = repack.load_v1_kernel_pin()
        candidate = repack.validate_pinned_v1_kernel(kernel_output, pin)
        if candidate["sha256"] != kernel_info["sha256"] or candidate["size_bytes"] != kernel_info["size_bytes"]:
            raise repack.RepackError("V1 candidate kernel differs from its verified OTA chain")
        kernel_info.update({"kind": "pinned_candidate", **candidate})
    else:
        if kernel_info["sha256"] != repack.BASE_KERNEL_SHA256 or kernel_info["size_bytes"] != STOCK_KERNEL_SIZE:
            raise repack.RepackError("V1 image without zram overlay must retain the original stock kernel")
        kernel_info["kind"] = "stock"
    return {"kernel": kernel_info, "zram_overlay": has_zram}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ota-dir", required=True, type=pathlib.Path)
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--kernel-output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    repack = load_repacker()
    try:
        result = validate_v1_image(args.ota_dir, args.root, args.kernel_output, repack)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"V1 kernel validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"V1 kernel verified: {result['kernel']['kind']}; zram overlay={result['zram_overlay']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
