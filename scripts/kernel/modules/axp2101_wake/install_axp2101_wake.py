#!/usr/bin/env python3
"""Install axp2101_wake.ko and its loader after axp2101.sh.

R1 only. The R3 II 2025 and TempoTec V1 pin, loader shape and module ABI
are not verified, and the R3 Pro II charges through the MP2731.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[4]
ARTIFACTS = REPO / "firmware/kernel/open-modules/axp2101_wake"
RECORD = ARTIFACTS / "axp2101_wake.json"
WAKE_BOARDS = ("r1",)
RAW_LINE = "sh axp2101_wake.sh\n"
WAKE_BLOCK = (
    'compas_startup_checkpoint module-before "axp2101_wake.sh" -\n'
    "sh axp2101_wake.sh\n"
    "_compas_module_status=$?\n"
    'compas_startup_checkpoint module-after "axp2101_wake.sh" "$_compas_module_status"\n'
    '(exit "$_compas_module_status")\n'
)
AXP_BLOCK = (
    'compas_startup_checkpoint module-before "axp2101.sh" -\n'
    "sh axp2101.sh\n"
    "_compas_module_status=$?\n"
    'compas_startup_checkpoint module-after "axp2101.sh" "$_compas_module_status"\n'
    '(exit "$_compas_module_status")\n'
)


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"install_axp2101_wake: {message}")


def load_record(record_path: pathlib.Path = RECORD) -> dict:
    if not record_path.is_file():
        fail(f"missing pin record {record_path}")
    return json.loads(record_path.read_text())


def insert_wake_loader(text: str) -> str:
    """Insert the wake loader after axp2101.sh. Idempotent. Fails closed."""
    if re.search(r"^sh[ \t]+axp2101_wake\.sh[ \t]*$", text, re.M):
        return text
    axp_calls = re.findall(r"^sh[ \t]+axp2101\.sh[ \t]*$", text, re.M)
    if len(axp_calls) != 1:
        fail("module loader must contain exactly one sh axp2101.sh")
    if "# COMPAS_STARTUP_TRACE_MODULES" in text:
        if text.count(AXP_BLOCK) != 1:
            fail("instrumented loader has no single axp2101.sh checkpoint block")
        return text.replace(AXP_BLOCK, AXP_BLOCK + WAKE_BLOCK, 1)
    match = re.search(r"^sh[ \t]+axp2101\.sh[ \t]*\n", text, re.M)
    if not match:
        fail("could not find sh axp2101.sh")
    return text[: match.end()] + RAW_LINE + text[match.end() :]


def install(root: pathlib.Path, artifacts: pathlib.Path = ARTIFACTS,
            record_path: pathlib.Path = RECORD) -> dict:
    """Copy the module and loader into root/module_driver and edit the init script."""
    record = load_record(record_path)
    entry = record["module"]
    ko_src = artifacts / "axp2101_wake.ko"
    sh_src = artifacts / "axp2101_wake.sh"
    for path, label in ((ko_src, "axp2101_wake.ko"), (sh_src, "axp2101_wake.sh")):
        if path.is_symlink() or not path.is_file():
            fail(f"{label} is missing or not a regular file: {path}")
    if sha(ko_src) != entry["sha256"]:
        fail(f"axp2101_wake.ko is {sha(ko_src)}, expected {entry['sha256']}")
    if sha(sh_src) != entry["loader_sha256"]:
        fail(f"axp2101_wake.sh is {sha(sh_src)}, expected {entry['loader_sha256']}")
    drivers = root / "module_driver"
    if drivers.is_symlink() or not drivers.is_dir():
        fail("unsafe or missing /module_driver")
    init = drivers / "driver_default_init_script.sh"
    if init.is_symlink() or not init.is_file():
        fail("unsafe or missing driver_default_init_script.sh")
    init.write_text(insert_wake_loader(init.read_text()))
    shutil.copy2(ko_src, drivers / "axp2101_wake.ko")
    shutil.copy2(sh_src, drivers / "axp2101_wake.sh")
    (drivers / "axp2101_wake.sh").chmod(0o755)
    return {
        "/module_driver/axp2101_wake.ko": entry["sha256"],
        "/module_driver/axp2101_wake.sh": entry["loader_sha256"],
    }


def main() -> None:
    if len(sys.argv) != 3:
        fail("usage: install_axp2101_wake.py BOARD ROOT")
    board, root = sys.argv[1], pathlib.Path(sys.argv[2])
    if board not in WAKE_BOARDS:
        fail(f"board {board} must not load axp2101_wake")
    install(root)
    print(f"installed axp2101_wake on {board}")


if __name__ == "__main__":
    main()
