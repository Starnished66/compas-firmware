#!/usr/bin/env python3
"""Rebuild the R1 modules that carry the HiBy v2.0 fixes (cw2015, soc_aic, lcd_lg35583).

The sources are the reconstructed drivers of the pinned hiby-custom-kernel commit
(firmware/kernel/upstream.json) with the reviewed module patches applied in name order:
compas-reconstructed-drivers-safety.patch, then compas-reconstructed-drivers-v2-fixes.patch.
They are built out of tree against the recorded Compás kernel tree (.config and System.map
pinned in firmware/r1_base_v2.json) with the Ingenic GCC 7.2 toolchain of the SDK archive named in
upstream.json (mips-gcc720-glibc229). Every pin must match or the build stops, and the result must
reproduce the pinned module hashes.

Usage:
  build_r1_v2_modules.py --kit HIBY_CUSTOM_KERNEL_CHECKOUT --kernel-tree CONFIGURED_KERNEL_TREE \\
      --toolchain SDK/prebuilts/toolchains/mips-gcc720-glibc229 --output DIR
          [--siblings DIR_OF_THE_OTHER_SHIPPED_MODULES]

The kernel tree is only read by Kbuild's out-of-tree mode; build against a copy of a recorded tree
to keep the original untouched. --siblings adds the other shipped modules (for example the
module_driver directory of the assembled base) to the undefined-symbol check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts/kernel/modules/verification"))
import verify_module_abi as abi  # noqa: E402

TOOL_FILES = {
    "gcc": "bin/mips-linux-gnu-gcc",
    "as": "bin/mips-linux-gnu-as",
    "ld": "bin/mips-linux-gnu-ld",
    "cc1": "libexec/gcc/mips-linux-gnu/7.2.0/cc1",
}
PATCH_GLOB = "compas-reconstructed-drivers-*.patch"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str):
    raise SystemExit(f"build_r1_v2_modules: {message}")


def run(*argv, **kw):
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def check_pins(args, pins: dict):
    tree = args.kernel_tree
    for rel, key in ((".config", "kernel_config_sha256"), ("System.map", "system_map_sha256")):
        if not (tree / rel).is_file() or sha(tree / rel) != pins[key]:
            fail(f"kernel tree {rel} does not match the pin in firmware/r1_base_v2.json")
    if not (tree / "Module.symvers").is_file():
        fail("kernel tree has no Module.symvers (it must be a built tree)")
    for name, rel in TOOL_FILES.items():
        path = args.toolchain / rel
        if not path.is_file() or sha(path) != pins["toolchain"][name]:
            fail(f"toolchain {rel} does not match the pin in firmware/r1_base_v2.json")
    patches = sorted(p for p in (REPO / "firmware/kernel/module-patches").glob(PATCH_GLOB))
    if [p.name for p in patches] != list(pins["patches"]):
        fail(f"module patches {[p.name for p in patches]} differ from the pinned list {list(pins['patches'])}")
    for p in patches:
        if sha(p) != pins["patches"][p.name]:
            fail(f"{p.name} does not match its pin")
    return patches


def export_sources(kit: pathlib.Path, commit: str, dest: pathlib.Path):
    try:
        run("git", "-C", kit, "cat-file", "-e", f"{commit}^{{commit}}")
    except subprocess.CalledProcessError:
        fail(f"{kit} is not a git checkout containing commit {commit}")
    archive = subprocess.run(["git", "-C", str(kit), "archive", commit, "modules", "boards/r1/modules"],
                             check=True, capture_output=True).stdout
    run("tar", "-x", "-C", dest, input=archive)


def module_dir(kit_tree: pathlib.Path, name: str) -> pathlib.Path:
    for base in ("modules", "boards/r1/modules"):
        if (kit_tree / base / name / "Makefile").is_file():
            return kit_tree / base / name
    fail(f"no source directory for {name}")


def build(args, pins: dict, commit: str):
    patches = check_pins(args, pins)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.glob("*.ko")):
        fail(f"output directory already holds modules: {out}")
    env = dict(os.environ, PATH=f"{args.toolchain / 'bin'}:{os.environ['PATH']}")
    with tempfile.TemporaryDirectory(prefix="r1-v2-modules.") as tmp:
        tmp = pathlib.Path(tmp)
        src = tmp / "kit"
        src.mkdir()
        export_sources(args.kit, commit, src)
        for patch in patches:
            run("patch", "--batch", "--forward", "--fuzz=0", "-s", "-p1", "-d", src, "-i", patch)
        built = {}
        for name in pins["modules"]:
            work = tmp / "ext" / name
            shutil.copytree(module_dir(src, name), work)
            run("make", "-C", args.kernel_tree, "ARCH=mips", "CROSS_COMPILE=mips-linux-gnu-",
                "HOSTCC=gcc -fcommon", f"M={work}", "HIBY_MODEL=r1", "modules", env=env,
                stdout=subprocess.DEVNULL)
            ko = work / f"{name}.ko"
            if not ko.is_file():
                fail(f"{name}.ko was not produced")
            if sha(ko) != pins["modules"][name]:
                fail(f"{name}.ko is {sha(ko)}, expected {pins['modules'][name]}")
            shutil.copy2(ko, out / f"{name}.ko")
            built[name] = sha(ko)
    return built


def verify(args, pins: dict):
    """Vermagic and undefined symbols of the rebuilt modules against System.map and their siblings."""
    out = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix="r1-v2-abi.") as tmp:
        tmp = pathlib.Path(tmp)
        vendor = tmp / "siblings"
        vendor.mkdir()
        if args.siblings:
            for ko in sorted(args.siblings.glob("*.ko")):
                if ko.name[:-3] not in pins["modules"]:
                    shutil.copy2(ko, vendor / ko.name)
        for ko in out.glob("*.ko"):
            shutil.copy2(ko, vendor / ko.name)
        empty = tmp / "built"
        empty.mkdir()
        report = abi.verify(args.kernel_tree / "System.map", empty, vendor,
                            shutil.which("nm") or "nm", shutil.which("modinfo") or "modinfo")
    if not report["valid"]:
        fail(f"ABI check failed: {report['vermagic_errors']} {report['missing_imports_by_module']}")
    (out / "abi-report.json").write_text(json.dumps(
        {k: report[k] for k in ("valid", "system_map_sha256", "vermagic_values",
                                "missing_imports_by_module", "selected_module_count")},
        indent=2, sort_keys=True) + "\n")
    return report["vermagic_values"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", required=True, type=pathlib.Path)
    ap.add_argument("--kernel-tree", required=True, type=pathlib.Path)
    ap.add_argument("--toolchain", required=True, type=pathlib.Path)
    ap.add_argument("--output", required=True, type=pathlib.Path)
    ap.add_argument("--siblings", type=pathlib.Path)
    args = ap.parse_args()
    args.kit, args.kernel_tree, args.toolchain = (p.resolve() for p in (args.kit, args.kernel_tree, args.toolchain))
    for tool in ("git", "make", "patch", "tar", "nm", "modinfo"):
        if not shutil.which(tool):
            fail(f"required command is unavailable: {tool}")
    pins = json.loads((REPO / "firmware/r1_base_v2.json").read_text())["module_build"]
    commit = json.loads((REPO / "firmware/kernel/upstream.json").read_text())["commit"]
    built = build(args, pins, commit)
    vermagic = verify(args, pins)
    for name, digest in sorted(built.items()):
        print(f"{digest}  {name}.ko")
    print(f"vermagic: {', '.join(vermagic)}")


if __name__ == "__main__":
    main()
