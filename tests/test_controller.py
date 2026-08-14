#!/usr/bin/env python3
import json
import stat
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asahi_fan_control import Controller, DEFAULT_CONFIG, Hardware, interpolate_curve


def write(path: Path, value, mode=0o644):
    path.write_text(str(value), encoding="ascii")
    path.chmod(mode)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        hw = self.root / "hwmon0"
        hw.mkdir()
        write(hw / "name", "macsmc_hwmon")
        for i, label in [(1, "Left fan"), (2, "Right fan")]:
            write(hw / f"fan{i}_label", label)
            write(hw / f"fan{i}_input", 2000)
            write(hw / f"fan{i}_target", 0)
            write(hw / f"fan{i}_min", 1200)
            write(hw / f"fan{i}_max", 6000)
        write(hw / "temp1_label", "CPU Performance Core")
        write(hw / "temp1_input", 60000)
        write(hw / "temp2_label", "Battery")
        write(hw / "temp2_input", 80000)
        self.config = json.loads(json.dumps(DEFAULT_CONFIG))
        self.config_path = self.root / "config.json"
        self.hardware = Hardware(self.root, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_discovers_and_excludes_battery(self):
        self.assertEqual(len(self.hardware.fans), 2)
        self.assertEqual([s.label for s in self.hardware.sensors], ["CPU Performance Core"])

    def test_curve_interpolation(self):
        self.assertEqual(interpolate_curve([[50, 20], [70, 60]], 60), 40)
        self.assertEqual(interpolate_curve([[50, 20], [70, 60]], 90), 60)

    def test_auto_activates_above_threshold(self):
        controller = Controller(self.hardware, self.config, self.config_path)
        controller.tick()
        self.assertTrue(controller.override_active)
        self.assertGreater(self.hardware.fans[0].target, self.hardware.fans[0].minimum)

    def test_smc_mode_writes_zero(self):
        controller = Controller(self.hardware, self.config, self.config_path)
        controller.tick()
        controller.set_mode("smc")
        self.assertEqual(self.hardware.fans[0].target, 0)

    def test_critical_forces_maximum(self):
        write(self.root / "hwmon0/temp1_input", 101000)
        controller = Controller(self.hardware, self.config, self.config_path)
        controller.tick()
        self.assertEqual(self.hardware.fans[0].target, 6000)

    def test_missing_temperature_fails_safe_at_maximum(self):
        (self.root / "hwmon0/temp1_input").unlink()
        controller = Controller(self.hardware, self.config, self.config_path)
        controller.tick()
        self.assertEqual(self.hardware.fans[0].target, 6000)
        self.assertIn("sem leitura", controller.last_error)

    def test_auto_returns_to_smc_below_hysteresis(self):
        controller = Controller(self.hardware, self.config, self.config_path)
        controller.tick()
        self.assertTrue(controller.override_active)
        write(self.root / "hwmon0/temp1_input", 49000)
        controller.tick()
        self.assertFalse(controller.override_active)
        self.assertEqual(self.hardware.fans[0].target, 0)


if __name__ == "__main__":
    unittest.main()
