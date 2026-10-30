#!/usr/bin/env python3
"""Build the Compás R1 base image on HiBy R1 v2.0.

Inputs (all pinned by SHA-256 in firmware/r1_base_v2.json):
  --v2-upt   HiBy R1 v2.0 firmware
  --base-upt the current staging-image-base r1.upt; it supplies the Compás kernel, 20 of the 23 rebuilt
             modules and the base-system layer (BlueALSA 5, BlueZ 5.87, GLib, D-Bus, Compás boot files)
  --rebuilt-modules  directory with cw2015.ko, soc_aic.ko and lcd_lg35583.ko from
             scripts/kernel/modules/build/build_r1_v2_modules.py (they carry the HiBy v2.0 fixes and
             replace the base's older builds)
  --system-map the pinned System.map; the final module set is checked against it
  --clean-binaries  directory (same layout as the rootfs) with the base-system layer binaries rebuilt
             without the builder's home path in them; each replaces the base's file of the same path
             and both hashes are pinned in "base_layer_clean_rebuilds"

The result keeps that base and swaps in HiBy v2.0's driver scripts, vendor modules, Wi-Fi/Bluetooth
firmware and the AIC8800 userspace. It writes usr/share/compas/vendor-driver-provenance.json
(schema 2) with the origin and hash of every module, firmware file and replaced script.
Usage: build_r1_base_v2.py --v2-upt V2.upt --base-upt BASE.upt --rebuilt-modules DIR \\
           --system-map System.map --clean-binaries DIR --output r1.upt [--work DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/kernel/modules/verification"))
import verify_module_abi as abi  # noqa: E402
MAX_BYTES = 45 * 1024 * 1024
CHUNK = 512 * 1024
SOC_PROBE = '''# COMPAS_MSC0_FREQUENCY: msc0 is the radio SDIO bus. HiBy v2.0 lowers it to 40 MHz for the
# AIC8800 (X1600EN/HN). X1600E (Broadcom) keeps 50 MHz, and so does any unidentified SoC.
msc0_max_frequency=50000000
if [ -r /sys/module/axp2101/parameters/detected_soc_id_valid ] &&
    [ -r /sys/module/axp2101/parameters/detected_soc_id ]; then
    case "$(cat /sys/module/axp2101/parameters/detected_soc_id_valid)" in
        Y|y|1)
            case "$(cat /sys/module/axp2101/parameters/detected_soc_id)" in
                18944|0x4A00|0x4a00|18688|0x4900) msc0_max_frequency=40000000 ;;
            esac
            ;;
    esac
fi
'''


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(*argv, **kw):
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def fail(message: str):
    raise SystemExit(f"build_r1_base_v2: {message}")


def require_pin(path: pathlib.Path, want: str, label: str):
    if sha(path) != want:
        fail(f"{label} SHA-256 does not match firmware/r1_base_v2.json: {path}")


def unpack_upt(upt: pathlib.Path, out: pathlib.Path):
    """Return (root_dir, xImage_path, ota_dir); verifies each image's size and MD5 from ota_update.in."""
    iso = out / "iso"
    run("7z", "x", "-y", f"-o{iso}", upt, stdout=subprocess.DEVNULL)
    ota = iso / "ota_v0"
    meta, entry = {}, {}
    for line in (ota / "ota_update.in").read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "img_type":
            entry = meta.setdefault(value, {})
        elif entry is not None and key != "ota_version":
            entry[key] = value
    images = {}
    for kind, name in (("kernel", "xImage"), ("rootfs", "rootfs.squashfs")):
        chunks = sorted(p for p in ota.iterdir() if re.fullmatch(re.escape(name) + r"\.[0-9]{4}\.[0-9a-f]{32}", p.name))
        target = out / name
        with target.open("wb") as dst:
            for chunk in chunks:
                dst.write(chunk.read_bytes())
        if target.stat().st_size != int(meta[kind]["img_size"]) or \
                hashlib.md5(target.read_bytes()).hexdigest() != meta[kind]["img_md5"]:
            fail(f"{upt.name}: {name} size or MD5 does not match ota_update.in")
        images[name] = target
    root = out / "root"
    run("unsquashfs", "-no-xattrs", "-d", root, images["rootfs.squashfs"], stdout=subprocess.DEVNULL)
    listing = subprocess.run(["unsquashfs", "-ll", images["rootfs.squashfs"]], check=True,
                             capture_output=True, text=True).stdout
    if re.search(r"^[cb]\S{9}\s", listing, re.M):
        fail(f"{upt.name}: device nodes cannot be repacked without root")
    return root, images["xImage"], ota


def inventory(root: pathlib.Path) -> dict:
    out = {}
    for parent, dirs, files in os.walk(root):
        for name in dirs + files:
            p = pathlib.Path(parent) / name
            rel = "/" + str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("L", os.readlink(p))
            elif p.is_file():
                out[rel] = ("F", sha(p), p.stat().st_mode & 0o7777)
            else:
                out[rel] = ("D", p.stat().st_mode & 0o7777)
    return out


def replace_once(path: pathlib.Path, old: str, new: str):
    text = path.read_text()
    if text.count(old) != 1:
        fail(f"{path.name}: expected exactly one {old!r}")
    path.write_text(text.replace(old, new))


def copy_file(src: pathlib.Path, dst: pathlib.Path):
    if src.is_symlink() or not src.is_file():
        fail(f"missing regular file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)


def file_map(root: pathlib.Path, rels, origins: dict) -> dict:
    out = {}
    for rel in rels:
        for parent, dirs, files in os.walk(root / rel):
            dirs.sort()
            for name in sorted(dirs + files):
                p = pathlib.Path(parent) / name
                key = "/" + str(p.relative_to(root))
                prefixes = [k for k in origins if k != "*" and (key == k or key.startswith(k + "/"))]
                origin = origins[max(prefixes, key=len)] if prefixes else origins["*"]
                if p.is_symlink():
                    out[key] = {"symlink": os.readlink(p), "origin": origin}
                elif p.is_file():
                    out[key] = {"sha256": sha(p), "size": p.stat().st_size, "origin": origin}
    return out


def set_config_version(root: pathlib.Path, v2_root: pathlib.Path) -> dict:
    """The staging base still names an earlier build in usr/resource/config.json ("version"); report HiBy 2.0's."""
    pattern = re.compile(r'("version"\s*:\s*)"([^"]*)"')
    want = pattern.search((v2_root / "usr/resource/config.json").read_text())
    path = root / "usr/resource/config.json"
    text = path.read_text()
    if not want or len(pattern.findall(text)) != 1:
        fail("usr/resource/config.json has no single string \"version\" to update")
    path.write_text(pattern.sub(lambda m: f'{m.group(1)}"{want.group(2)}"', text))
    return {"/usr/resource/config.json": f'"version" -> HiBy 2.0\'s {want.group(2)} (the other settings stay the base\'s)'}


def apply_script_edits(drivers: pathlib.Path, pol: dict) -> dict:
    """Compás policy edits to HiBy's v2.0 driver scripts; returns {path: edit description}."""
    axp = drivers / "axp2101.sh"
    replace_once(axp, "charge_voltage_limit=4400", f"charge_voltage_limit={pol['charge_voltage_limit']}")
    replace_once(axp, "charge_term_current=100", f"charge_term_current={pol['charge_term_current']}")
    text = axp.read_text()
    # v2.0 raises bldo1/bldo2 (LCD supplies) from 2.8 to 3.0 V for every unit. Not needed for the
    # AIC radio, so X1600E keeps the 2.8 V it has always run at.
    bldo = pol["bldo_work_voltage_uv"]
    if text.count("work_voltage=3000000 suspend_volage=3000000") != 2:
        fail("axp2101.sh no longer has the expected bldo1/bldo2 3.0 V settings")
    for name in ("bldo1", "bldo2"):
        text = re.sub(rf'(regulator_name={name} boot_on=disable )work_voltage=3000000 suspend_volage=3000000',
                      rf"\g<1>work_voltage={bldo} suspend_volage={bldo}", text)
    if "dcdc4_auto_x1600e_en_hn=1" not in text or text.count(f"work_voltage={bldo}") < 2:
        fail("axp2101.sh edit failed")
    axp.write_text(text)
    edits = {
        "/module_driver/axp2101.sh": "charging 4400/100 -> 4350 mV/70 mA; bldo1/bldo2 3.0 V -> 2.8 V; "
                                     "dcdc4_auto_x1600e_en_hn=1 kept",
    }
    if pol.get("msc0_probe"):
        # Optional: 40 MHz only on X1600EN/HN. Off by default; HiBy's loader ships unchanged.
        msc = drivers / "soc_msc.sh"
        replace_once(msc, "msc0_max_frequency=40000000", "msc0_max_frequency=$msc0_max_frequency")
        msc.write_text(SOC_PROBE + msc.read_text())
        edits["/module_driver/soc_msc.sh"] = "msc0 40 MHz only when axp2101 identifies X1600EN/HN, else 50 MHz"
    return edits


def weekly_userspace(m: dict, userspace: dict) -> dict:
    """The userspace files the weekly repack rewrites, with the base hash and the pinned final hash."""
    out = {}
    for rel, entry in m["weekly_repack_userspace"].items():
        if rel == "note":
            continue
        if rel not in userspace:
            fail(f"weekly_repack_userspace names {rel}, which is not a recorded userspace file")
        out[rel] = {"edit": entry["edit"], "base_sha256": userspace[rel]["sha256"],
                    "final_sha256": entry["final_sha256"]}
    return out


def verify_unmodified_radio(v2_root: pathlib.Path, root: pathlib.Path, kept: set) -> dict:
    """The radio drivers, their loaders and all /lib/firmware must equal HiBy v2.0's bytes."""
    rels = ["module_driver/cywdhd.ko", "module_driver/cywdhd.r1", "module_driver/soc_msc.ko",
            "module_driver/r1_wireless_select.sh", "module_driver/aic8800_bsp.r1",
            "module_driver/aic8800_fdrv.load"]
    rels += [f"module_driver/{p.name}" for p in sorted((v2_root / "module_driver").glob("aic8800_*.ko"))]
    for parent, _, names in os.walk(v2_root / "lib/firmware"):
        rels += [str((pathlib.Path(parent) / n).relative_to(v2_root)) for n in sorted(names)]
    out = {}
    for rel in rels:
        a, b = v2_root / rel, root / rel
        if b.is_symlink() or not b.is_file() or sha(a) != sha(b):
            fail(f"radio file differs from HiBy v2.0 (must ship unmodified): /{rel}")
        out["/" + rel] = sha(b)
    for parent, _, names in os.walk(root / "lib/firmware"):
        for n in names:
            rel = str((pathlib.Path(parent) / n).relative_to(root))
            if "/" + rel not in out and not any(rel.startswith(k + "/") for k in kept):
                fail(f"unexpected file in /lib/firmware: /{rel}")
    return out


def replace_clean_binaries(src, root: pathlib.Path, m: dict) -> dict:
    """Swap the pinned base-system layer binaries for their path-free rebuilds; returns the provenance."""
    spec = m.get("base_layer_clean_rebuilds")
    if not spec:
        return {}
    if src is None:
        fail("--clean-binaries is required: firmware/r1_base_v2.json pins base_layer_clean_rebuilds")
    out = {}
    for rel, pin in sorted(spec["files"].items()):
        target, built = root / rel, src / rel
        if target.is_symlink() or not target.is_file() or sha(target) != pin["pre_sha256"]:
            fail(f"base file /{rel} is not the pinned staging binary")
        if built.is_symlink() or not built.is_file() or sha(built) != pin["post_sha256"]:
            fail(f"clean rebuild of /{rel} is missing or does not match firmware/r1_base_v2.json")
        mode = target.stat().st_mode & 0o7777
        copy_file(built, target)
        target.chmod(mode)
        out["/" + rel] = {"sha256": pin["post_sha256"], "size": target.stat().st_size,
                          "replaced_sha256": pin["pre_sha256"]}
    return out


def check_module_set(system_map: pathlib.Path, drivers: pathlib.Path, m: dict):
    """Every module of the final set has the kernel's vermagic and resolves its imports against the
    pinned System.map and the other modules."""
    if sha(system_map) != m["kernel"]["system_map_sha256"]:
        fail("--system-map does not match the pinned System.map")
    with tempfile.TemporaryDirectory(prefix="r1-base-abi.") as empty:
        report = abi.verify(system_map, pathlib.Path(empty), drivers, shutil.which("nm") or "nm",
                            shutil.which("modinfo") or "modinfo")
    if not report["valid"]:
        fail(f"module ABI check failed: {report['vermagic_errors']} {report['missing_imports_by_module']}")


def build(args, m: dict, work: pathlib.Path):
    pol = m["policy"]
    v2_root, _, v2_ota = unpack_upt(args.v2_upt, work / "v2")
    root, kernel, _ = unpack_upt(args.base_upt, work / "base")
    require_pin(kernel, m["kernel"]["xImage_sha256"], "base kernel xImage")
    drivers = root / "module_driver"
    pinned = dict(m["compas_modules"])
    for name, want in pinned.items():
        if not (drivers / name).is_file() or sha(drivers / name) != want:
            fail(f"base module {name} is not the pinned Compás rebuild")
    stash = work / "compas-modules"
    stash.mkdir()
    for name in pinned:
        shutil.copy2(drivers / name, stash / name)
    # cw2015, soc_aic and lcd_lg35583 come from the HiBy v2.0 fixes rebuild, not from the base.
    fixed = {f"{k}.ko": v for k, v in m["module_build"]["modules"].items()}
    for name, want in fixed.items():
        built = args.rebuilt_modules / name
        if built.is_symlink() or not built.is_file() or sha(built) != want:
            fail(f"rebuilt module {name} is missing or does not match firmware/r1_base_v2.json")
        shutil.copy2(built, stash / name)
    pinned.update(fixed)
    for name in pinned:
        if not (v2_root / "module_driver" / name).is_file():
            fail(f"HiBy v2.0 has no {name}")
    brcm = work / "kept-brcm"
    for rel in m["kept_from_base"]:
        if not (root / rel).is_dir():
            fail(f"base lacks {rel}")
    shutil.copytree(root / m["kept_from_base"][0], brcm, symlinks=True)

    origins = {"*": "hiby-v2.0"}
    for name in pinned:
        origins[f"/module_driver/{name}"] = "compas-rebuild"
    source_files = file_map(v2_root, ["module_driver", "lib/firmware"], {"*": "hiby-v2.0"})

    shutil.rmtree(drivers)
    shutil.copytree(v2_root / "module_driver", drivers, symlinks=True)
    for name in pinned:
        shutil.copy2(stash / name, drivers / name)
    edits = apply_script_edits(drivers, pol)
    config_edit = set_config_version(root, v2_root)
    check_module_set(args.system_map, drivers, m)
    for key in edits:
        origins[key] = "hiby-v2.0+compas-edit"
    shutil.rmtree(root / "lib/firmware")
    shutil.copytree(v2_root / "lib/firmware", root / "lib/firmware", symlinks=True)
    shutil.copytree(brcm, root / m["kept_from_base"][0], symlinks=True)
    for rel in m["kept_from_base"]:
        origins["/" + rel] = "compas-base"

    unmodified = verify_unmodified_radio(v2_root, root, set(m["kept_from_base"]))
    for key in unmodified:
        origins[key] = "hiby-v2.0-unmodified"
    replaced = {}
    patched = []
    for rel in m["userspace_from_v2"]:
        dst = root / rel
        replaced[rel] = sha(dst) if dst.is_file() else None
        copy_file(v2_root / rel, dst)
    vw = m["vendor_wifi_on"]
    dst = root / vw["to"]
    replaced[vw["to"]] = sha(dst) if dst.is_file() else None
    copy_file(v2_root / vw["from"], dst)
    for entry in m["script_patches"]:
        target = root / entry["path"]
        if sha(target) != entry["pre_sha256"]:
            fail(f"{entry['path']} is not the pinned base script")
        patch_file = REPO / entry["patch"]
        run("patch", "--no-backup-if-mismatch", "-s", "-p1", "-d", root, "-i", patch_file)
        if sha(target) != entry["post_sha256"]:
            fail(f"{entry['path']} differs from the pinned patched script")
        patched.append(entry["path"])
    clean_rebuilds = replace_clean_binaries(args.clean_binaries, root, m)
    shutil.copy2(v2_ota / "ota_compatibility.in", work / "ota_compatibility.in")

    user_rels = list(m["userspace_from_v2"]) + [vw["to"]] + patched
    user_origin = {}
    for rel in user_rels:
        user_origin["/" + rel] = "compas-patch-of-base" if rel in patched else "hiby-v2.0"
    userspace = {}
    for rel in user_rels:
        p = root / rel
        userspace["/" + rel] = {"sha256": sha(p), "size": p.stat().st_size,
                                "origin": user_origin["/" + rel], "replaced_sha256": replaced.get(rel)}
    for rel in patched:
        userspace["/" + rel]["replaced_sha256"] = next(
            e["pre_sha256"] for e in m["script_patches"] if e["path"] == rel)

    kernel_meta = dict(m["kernel"])
    kernel_meta["kernel_xImage_sha256"] = kernel_meta.pop("xImage_sha256")
    v2 = m["hiby_v2_upt"]
    provenance = {
        "schema_version": 2,
        "board": "r1",
        "version": v2["version"],
        "release_date": "2026-10-08",
        "release_date_note": "date stamp of the UPT's entries; HiBy's announcement date is not recorded",
        "source_url": v2["source_url"],
        "archive_url": v2["source_url"],
        "upt_sha256": v2["sha256"],
        "archive_sha256": v2["sha256"],
        "kernel_xImage_sha256": kernel_meta["kernel_xImage_sha256"],
        "kernel": kernel_meta,
        "base_upt_sha256": m["staging_base_upt"]["sha256"],
        "builder": "scripts/base_image/build_r1_base_v2.py",
        "driver_init_policy": "HiBy v2.0 initialization sequence (r1_wireless_select.sh picks cywdhd or AIC8800)",
        "source_files": source_files,
        "installed_files": file_map(root, ["module_driver", "lib/firmware"], origins),
        "compas_rebuilt_modules": {
            "toolchain": m["module_build"]["toolchain_note"],
            "patches": m["module_build"]["patches"],
            "builder": "scripts/kernel/modules/build/build_r1_v2_modules.py",
            "hiby_v2_fixes": {f"{k}.ko": v for k, v in m["module_build"]["modules"].items()}},
        "unmodified_vendor_radio": {
            "policy": "Wi-Fi/Bluetooth drivers and firmware ship exactly as HiBy built them",
            "files": unmodified},
        "edited_scripts": {**edits, **config_edit},
        "userspace_files": userspace,
        "base_layer_clean_rebuilds": {
            "policy": "same sources, versions and patches as the staging base; rebuilt so no binary carries "
                      "the build machine's paths (scripts/build/base/*)",
            "files": clean_rebuilds},
        "preserved_parameters": {"module": "axp2101", "charge_voltage_limit": pol["charge_voltage_limit"],
                                 "charge_term_current": pol["charge_term_current"]},
        "weekly_repack_userspace": weekly_userspace(m, userspace),
        "weekly_repack_edits": {
            "/module_driver/cst8xx_touch.sh": "cst_max_touch_number 1 -> 2",
            "/module_driver/keyboard_adc_multifunc.sh": "adc_key_detectime 100 -> 20",
            "/module_driver/driver_default_init_script.sh": "startup-trace instrumentation",
        },
        "vendor_ota_compatibility_not_shipped": (work / "ota_compatibility.in").read_text().strip(),
    }
    target = root / "usr/share/compas/vendor-driver-provenance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    return root, kernel, work / "ota_compatibility.in"


def pack_image(image: pathlib.Path, name: str, dest: pathlib.Path):
    md5 = hashlib.md5(image.read_bytes()).hexdigest()
    data = image.read_bytes()
    chain = []
    previous = md5
    for i in range(0, len(data), CHUNK):
        part = data[i:i + CHUNK]
        part_md5 = hashlib.md5(part).hexdigest()
        (dest / f"{name}.{i // CHUNK:04d}.{previous}").write_bytes(part)
        chain.append(part_md5)
        previous = part_md5
    (dest / f"ota_md5_{name}.{md5}").write_text("\n".join(chain) + "\n")
    return len(data), md5


def package(root: pathlib.Path, kernel: pathlib.Path, compat: pathlib.Path, work: pathlib.Path, output: pathlib.Path):
    iso = work / "new-iso"
    ota = iso / "ota_v0"
    ota.mkdir(parents=True)
    rootfs = work / "new-rootfs.squashfs"
    run("mksquashfs", root, rootfs, "-comp", "lzo", "-all-root", "-noappend", "-no-xattrs",
        "-mkfs-time", "0", stdout=subprocess.DEVNULL)
    rsize, rmd5 = pack_image(rootfs, "rootfs.squashfs", ota)
    ksize, kmd5 = pack_image(kernel, "xImage", ota)
    (ota / "ota_update.in").write_text(
        f"ota_version=0\nimg_type=kernel\nimg_name=xImage\nimg_size={ksize}\nimg_md5={kmd5}\n"
        f"img_type=rootfs\nimg_name=rootfs.squashfs\nimg_size={rsize}\nimg_md5={rmd5}\n")
    shutil.copy2(compat, ota / "ota_compatibility.in")
    (ota / "ota_v0.ok").write_text("")
    (iso / "ota_config.in").write_text("current_version=0\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    run("genisoimage", "-f", "-U", "-J", "-joliet-long", "-r", "-allow-lowercase", "-allow-multidot",
        "-o", output, iso, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if output.stat().st_size > MAX_BYTES:
        fail(f"image is {output.stat().st_size} bytes, over the 45 MiB limit")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-upt", required=True, type=pathlib.Path)
    ap.add_argument("--base-upt", required=True, type=pathlib.Path)
    ap.add_argument("--rebuilt-modules", required=True, type=pathlib.Path)
    ap.add_argument("--system-map", required=True, type=pathlib.Path)
    ap.add_argument("--clean-binaries", type=pathlib.Path,
                    help="rebuilt base-system layer binaries, laid out like the rootfs")
    ap.add_argument("--output", required=True, type=pathlib.Path)
    ap.add_argument("--work", type=pathlib.Path, help="scratch directory (default: a temporary one)")
    args = ap.parse_args()
    args.rebuilt_modules, args.system_map = args.rebuilt_modules.resolve(), args.system_map.resolve()
    if args.clean_binaries is not None:
        args.clean_binaries = args.clean_binaries.resolve()
    for tool in ("7z", "unsquashfs", "mksquashfs", "genisoimage", "patch", "nm", "modinfo"):
        if not shutil.which(tool):
            fail(f"required command is unavailable: {tool}")
    m = json.loads((REPO / "firmware/r1_base_v2.json").read_text())
    require_pin(args.v2_upt, m["hiby_v2_upt"]["sha256"], "HiBy v2.0 UPT")
    require_pin(args.base_upt, m["staging_base_upt"]["sha256"], "staging base UPT")
    own = args.work is None
    work = pathlib.Path(tempfile.mkdtemp(prefix="r1-base-v2.")) if own else args.work.resolve()
    if not own:
        work.mkdir(parents=True, exist_ok=True)
        if any(work.iterdir()):
            fail(f"--work must be empty: {work}")
    try:
        root, kernel, compat = build(args, m, work)
        package(root, kernel, compat, work, args.output.resolve())
        # Re-open the result and confirm it is exactly the tree that was built.
        check = work / "check"
        check.mkdir()
        new_root, new_kernel, _ = unpack_upt(args.output.resolve(), check)
        if inventory(new_root) != inventory(root) or sha(new_kernel) != m["kernel"]["xImage_sha256"]:
            fail("the packed image does not match the assembled tree")
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)
    print(f"Created {args.output} ({args.output.stat().st_size} bytes)")
    print(f"{sha(args.output.resolve())}  {args.output.name}")


if __name__ == "__main__":
    main()
