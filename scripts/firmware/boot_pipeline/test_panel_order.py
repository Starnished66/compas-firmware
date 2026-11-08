#!/usr/bin/env python3
"""Check panel scheduling without changing module calls or trace pairing."""
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "startup_trace", ROOT / "scripts/firmware/boot_pipeline/install_startup_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)

PREFIX = ["utils", "rmem_manager", "soc_utils", "soc_i2c", "i2c_gpio_add", "axp2101",
          "cw2015", "keyboard_gpio_add", "soc_gpio", "soc_pwm", "pwm_backlight"]
TAIL = ["soc_fb", "soc_aic", "soc_msc", "r1_wireless_select", "soc_adc", "lcd_lg35583",
        "sa_sound_switch", "codec_cs43131", "cst8xx_touch", "keyboard_adc_multifunc"]


def source(names):
    return "#!/bin/sh\n\n" + "".join(f"sh {name}.sh\n" for name in names)


class PanelOrderTests(unittest.TestCase):
    def test_prerequisites_and_remaining_order_preserved(self):
        traced = trace.instrument_modules(source(PREFIX + TAIL))
        result = trace.prioritize_panel(traced)
        calls = re.findall(r"^sh (.*)\.sh$", result, re.MULTILINE)
        self.assertEqual(calls, PREFIX + ["soc_fb", "soc_adc", "lcd_lg35583"] +
                         TAIL[1:4] + TAIL[6:])
        self.assertEqual(sorted(result.splitlines()), sorted(traced.splitlines()))
        self.assertEqual(trace.instrument_modules(result), result)
        self.assertEqual(trace.prioritize_panel(result), result)

    def test_unknown_or_incomplete_dependencies_unchanged(self):
        for names in [PREFIX[1:] + TAIL, PREFIX + TAIL + ["soc_adc"],
                      PREFIX + TAIL[:3] + ["cywdhd"] + TAIL[4:],
                      PREFIX + ["soc_fb", "soc_adc", "lcd_other"]]:
            with self.subTest(names=names):
                traced = trace.instrument_modules(source(names))
                self.assertEqual(trace.prioritize_panel(traced), traced)


if __name__ == "__main__":
    unittest.main()
