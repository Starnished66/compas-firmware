# Release checklist

Follow this before every Compás release, whether a person or an agent prepares it. Tick each item; if one fails, stop and fix it before going on. A release is a published GitHub release of compas-player (firmware images) or Compás Tools; weekly betas from this repository follow the same checks, except the hardware and owner steps marked *(stable only)*.

## 1. Source

- [ ] Every repository involved is on the commit you intend to release, with a clean working tree (`git status` shows nothing).
- [ ] All four boards build from compas-player `main`: `r1`, `r3proii`, `r3ii_2025` and `tempotec_v1`.
- [ ] Commits have the owner as author and short messages, with no `Co-Authored-By` or other trailers.
- [ ] Nothing in any public repository, binary or image points to the private website repository (`compas-page`). Check with `git grep compas-page` and `strings` on each player.
- [ ] No secrets, tokens, PINs, passwords, personal paths (`/home/...`), Wi-Fi names or MAC addresses in tracked files or in the new commits.
- [ ] New features only add behaviour: existing settings, defaults and screens behave as before unless the release notes say otherwise.

## 2. Version label

- [ ] Each player is built with `make release BOARD=<board> RELEASE_LABEL=<label>`, never plain `make target`.
- [ ] The label is `vX.Y.Z` (or `Compas vX.Y.Z`) for a stable release, or `Weekly Beta YYYY-MM-DD` for a weekly. Labels with "Compás" (accented) are rejected by the build because the player's updater can't parse them.
- [ ] Each player binary contains exactly one `vX.Y.Z` string, equal to the release version, and no `Development Build`:
  `grep -a -o 'v[0-9]*\.[0-9]*\.[0-9]*' compas_player_target | sort -u` and `grep -ac 'Development Build' compas_player_target` (must print 0).
- [ ] The board marker is right for each binary: `grep -a -o 'COMPAS_PLAYER_BOARD:[a-z0-9_]*' <player> | sort -u`.
- [ ] The GitHub release tag and title match the label (`v1.3.1` / "Compás v1.3.1"; weeklies use the tag `weekly-beta-YYYY-MM-DD`).

## 3. Images

- [ ] Inputs are fetched with `scripts/build/firmware/fetch_inputs.sh` and every hash in `firmware/inputs.sha256` and `firmware/ssc-overlay.sha256` checks out.
- [ ] `scripts/tests/run_all.sh` passes.
- [ ] `scripts/build/firmware/build_all_upt.sh` finishes for all four boards and `scripts/build/firmware/validate_images.sh` passes for each (branding, player marker, `ota_update.in` format, `v1_md5.txt`).
- [ ] Compared with the previous release, each image changes only where expected: unpack both rootfs (`unsquashfs`) and diff the file list, modes and contents; the kernel (`xImage`) is byte-identical unless the release changes it on purpose.
- [ ] Every image is at most 45 MiB.
- [ ] `SHA256SUMS` lists every asset and `sha256sum -c SHA256SUMS` passes; `v1_md5.txt` matches `v1.upt`.
- [ ] Re-download the published assets from GitHub and check them again with `sha256sum -c` (GitHub may rename files with spaces or accents).

## 4. Compás Tools and the apps

- [ ] Compás Tools, as already released, reads the new version from each player (it reads the single `vX.Y.Z` from the running program) and offers the right update. Tools must not need a new release to recognise a new player version.
- [ ] The player's own online updater sees the release as newer than the previous one and not as newer than itself once installed.
- [ ] For a Compás Tools or Android app release: the version in every manifest is bumped, CI is green, and the installers are built from the tagged commit.

## 5. Hardware *(stable only)*

- [ ] Installed and run on each board it ships for (R1, R3 Pro II, R3 II 2025, TempoTec V1), from the SD card or a flashed `.upt`, never by other means.
- [ ] After install: About shows the release version, playback works on wired and Bluetooth output, the library loads, and Wi-Fi, Remote Control and the queue are kept.
- [ ] Anything new in the release was tried on the device.

## 6. Notes and publishing *(stable only)*

- [ ] Release notes are short, written by a person for people, and say what changed and what users need to do.
- [ ] The owner has read the notes and approved publishing.
- [ ] Releases stay drafts until the owner has tested them on hardware.
- [ ] Builds that are not signed say so, with the steps to open them on Windows and macOS.
- [ ] GPL: the release notes link to the kernel and base-system sources and patches in this repository (`firmware/kernel/KERNELS.md`).

## 7. After publishing

- [ ] The release is marked latest only if it is a stable release; weeklies are prereleases.
- [ ] The download page on compasplayer.org shows the new version.
- [ ] Test or temporary releases created while checking are deleted, with their tags.
