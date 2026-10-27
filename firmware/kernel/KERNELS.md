# Shipped kernels: provenance and corresponding source

The weekly build does **not** compile a kernel. Every image takes `xImage` unchanged from its base
(`staging-image-base` for HiBy boards, the official TempoTec image for the V1), so the kernels in a
release are the ones below. This folder holds the source-side material (config fragments, patches,
module sources, pins); the kernel itself is GPL-2.0.

Upstream pin: `firmware/kernel/upstream.json` (Jepl4r/hiby-custom-kernel `e1c5915290197ba01297e3f7c53f37197e0b1f9c`,
Ingenic X1600 SDK `ingenic-linux-kernel4.4.94-x1600-v6.0-20240606`, Linux 4.4.94+).

| Board | xImage SHA-256 | Origin | Config / patches here | Notes |
| --- | --- | --- | --- | --- |
| r1 | `2105616e27468bb869f7cb5da6e615204c1a2cf83a586f07dd036b5f88394efd` | Compás build of the pinned kernel source, shipped in `staging-image-base`; vendor driver payload HiBy R1 1.8.b2 (`firmware/vendor_drivers.json`) | `r1-parity.config`, `r1-optimized.config`, `compas-r1-brcmfmac.config` (experimental Wi-Fi only), `patches/`, `display-experimental/` | Exact build commit and compiled `.config` hash of this binary are **not recorded**. |
| r3proii | `ea31d8b49ecdb9667b0983ffa710de31edafbcd34d9c7c448d240de99590aafc` | Compás build of the pinned source | `configs/r3proii/*`, `patches/compas-dma-signed-gaps.patch`, `patches/compas-usb-dac-safety.patch`, `open-modules/r3proii.json` (config hash `9bb45e73...`, System.map hash) | Pinned in `open-modules/r3proii.json`. |
| r3ii_2025 | `9a05ad42b134c4cb26a573e18d8b1ca09844e3d6454a817f767496e41e0c2ddb` | Compás build of the pinned source | `configs/r3ii_2025/*`, `patches/` | Compiled config hash `0fab5106...` and System.map `b54c61f2...` were recorded at v1.1 for this kernel size class; the link to this exact binary is **unverified**. |
| tempotec_v1 | `3a83176b9d8da6c09eedd64348ea8a612ad5ee2ae532ce04ccadd7d0fa4bb25d` | Official TempoTec V1 1.2 firmware (Linux 4.4.94+), unmodified | none (vendor binary) | Vendor GPL source offer applies; no Compás patches. |

Kernel modules: `module-patches/` (radio lifecycle/input safety, reconstructed-driver safety),
`open-modules/` (the open `gt9xx_touch.ko` for the R3 Pro II, source pin in its json), and the
vendor `.ko` files carried in each base image.

Items marked "not recorded" or "unverified" are unknown to this repository today; they should be filled in
from the original build logs when found, or the kernels rebuilt and the hashes updated.

## Source requests

The exact build commit and compiled `.config` of the **r1** kernel (and the config of the r3ii_2025 kernel) are
**unknown** in this repository. For source or build details of any shipped kernel, open an issue on this repository
and the corresponding source will be provided; the pinned upstream is listed above.
