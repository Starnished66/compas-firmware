# TempoTec Variations V1: hardware notes

The V1 is HibyOS on an Ingenic X1600, the same class of machine as the R1 and R3 Pro II, with a 240x320
panel. Compás does not replace its kernel or audio drivers. How the image is built is in
[inputs.md](inputs.md) and `scripts/firmware/package/repack_v1_upt.py`.

## Attribution

The button map and the jack note below come from the Sonix V1 fork
(`mr-f0xx/sonix-player-tempotec-v1`), which has been run on a V1. They are observations from that
fork, not guesses from a datasheet. The "Stock V1.2 firmware" section was read from TempoTec's own
`v1.upt` 1.2 (SHA-256 `9f929a92...fa05d`, see [inputs.md](inputs.md)).

## Buttons

Left flank: Volume Up, Volume Down, then the microSD slot. Right flank, top to bottom: Power,
Previous, Play, Next.

The V1 kernel labels the two skip keys backwards, as the R3 Pro II does. On `md-gpio-keys` and
`jz adc keyboard`:

| Kernel code | Physical key |
| --- | --- |
| `KEY_NEXTSONG` | Previous |
| `KEY_PREVIOUSSONG` | Next |
| `KEY_PLAYPAUSE` | Play |
| `KEY_VOLUMEUP` / `KEY_VOLUMEDOWN` | Volume |
| `KEY_POWER` | Power |

A cable remote (`earpods_adc`) and Bluetooth AVRCP are not swapped. The stock loaders agree:
`keyboard_gpio_add.sh` maps Power (PC31) and `KEY_PREVIOUSSONG` (PC28); `keyboard_adc.sh` maps
`KEY_PLAYPAUSE`, `KEY_NEXTSONG`, Volume Up and Volume Down on ADC channel 0.

## Jack and outputs

`/sys/class/switch` on the measured V1 has `headset` only, no `balance`. That node reads `1` with
both sockets empty, so `1` is unplugged. Any other value is still reported as the 3.5 mm jack until a
plug is measured. The V1 has two CS43198 DACs (stock `codec_cs43198_dual.ko`) and both a 3.5 mm and a
4.4 mm jack, so it must not take the R1 single-DAC shortcut.

## Stock V1.2 firmware

- Charging: `axp2101.sh` loads `charge_voltage_limit=4400 charge_term_current=100`. The R1 uses
  4350 mV and 70 mA. Compás keeps its charger writes off and leaves the stock limits in place.
- USB role: the V1 has the R1's TCS1421 Type-C switch (`tcs1421_add.ko`, CFG GPIOs PA20/PA21), and the
  stock player writes `/sys/devices/platform/tcs1421/tcs1421_cfg`, the R1's node. The R1 role code
  stays off on the V1 until it is tried on a device.
- Touch: `cst8xx_touch.sh` reports 0-240 x 0-320, no flip or swap, one contact. It is used as shipped.
  (The V1's driver is also Hynitron (`hyn_ts`), but its ABS range is the 240x320 panel, so the R1 pixel-coordinate exception is not needed.)
- Jacks: `sa_sound_switch.sh` sets up `headset` only (ADC channel 1, 0-3300 -> 1) with every
  `balance` field `-1`, so the stock kernel never reports a 4.4 mm switch. The stock player selects the
  port itself (`ot_device_analog_switch_port headset` and `... balance`) and drives the two CS43198s
  through `codec_cs43198_dual.ko`.

## Boot artwork

The V1 splash script picks `/etc/logo.jpeg`, `logo1.jpeg` or `logo2.jpeg` from a NAND theme flag. The
packager installs one 240x320 image for all three and a 240x320 `boot_animation/en/0.jpg` and `0.png`
(`assets/v1/`, provenance in `assets/boot-artwork-source.txt`).

## Still open

- Route selection between the 3.5 mm and 4.4 mm outputs.
- On-device proof: boot, touch, every key, both jacks, sleep and wake, library scan, Wi-Fi, Bluetooth,
  update, and restoring stock by flashing TempoTec's `v1.upt` from the SD card.
