"""Factory + linear-regression calibration and the UI-version setting.

    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import regression, settings    # noqa: E402


def _factory():
    with open(os.path.join(ROOT, "calibration_default.json")) as fh:
        return json.load(fh)


def _captures_from(factory, transform, positions=("out", "9cm", "11cm"), sd=0.5):
    caps = {}
    for pos in positions:
        caps[pos] = {int(pin): (transform(int(pin), rep["levels"][pos]), sd)
                     for pin, rep in factory["report"].items()}
    return caps


class FitLineTest(unittest.TestCase):
    def test_exact_line(self):
        a, b, r2 = regression.fit_line([(0, 5), (10, 25), (20, 45)])
        self.assertAlmostEqual(a, 2.0)
        self.assertAlmostEqual(b, 5.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_noisy_line_r2(self):
        a, b, r2 = regression.fit_line([(0, 0), (10, 12), (20, 19), (30, 31)])
        self.assertGreater(r2, 0.95)
        self.assertAlmostEqual(a, 1.0, delta=0.1)

    def test_needs_spread(self):
        with self.assertRaises(ValueError):
            regression.fit_line([(5, 1), (5, 2)])


class CalibrateTest(unittest.TestCase):
    def setUp(self):
        self.f = _factory()
        self.fthr = {int(k): v for k, v in self.f["trigger_delta_overrides"].items()}

    def test_identity_reproduces_factory(self):
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: v))
        for pin, p in res["pins"].items():
            self.assertAlmostEqual(p["a"], 1.0, places=2)
            self.assertAlmostEqual(p["b"], 0.0, delta=2)
            self.assertAlmostEqual(p["threshold"], self.fthr[pin], delta=1)

    def test_offset_shift_is_learned(self):
        # e.g. GPIO 15 sat 28 ADC higher after re-seating
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: v + 28))
        p15 = res["pins"][15]
        self.assertEqual(p15["mode"], "regression")
        self.assertAlmostEqual(p15["a"], 1.0, places=2)
        self.assertAlmostEqual(p15["b"], 28, delta=1)
        self.assertEqual(res["calibrated_levels"]["15"][0], 815 + 28)

    def test_gain_change_scales_trigger(self):
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: 1.5 * v - 100))
        p7 = res["pins"][7]
        self.assertAlmostEqual(p7["a"], 1.5, places=2)
        self.assertGreater(p7["threshold"], self.fthr[7])          # bigger signal
        self.assertLessEqual(p7["threshold"], 2 * self.fthr[7])    # clamped

    def test_entry_level_mapped_without_capturing_it(self):
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: v + 10))
        self.assertEqual(res["pins"][17]["levels"]["entry"],
                         self.f["report"]["17"]["levels"]["entry"] + 10)

    def test_poor_fit_falls_back_to_offset(self):
        # entry pins while *held* at 9 cm read near "out" (seen on the trainer)
        def held(p, v):
            return v if p not in (17, 18) else self.f["report"][str(p)]["levels"]["out"] - 30
        caps = _captures_from(self.f, held)
        caps["out"] = {int(k): (r["levels"]["out"], 0.5) for k, r in self.f["report"].items()}
        res = regression.calibrate(self.f, caps)
        p17 = res["pins"][17]
        self.assertEqual(p17["mode"], "offset")
        self.assertEqual(p17["a"], 1.0)
        self.assertGreaterEqual(p17["threshold"], 0.5 * self.fthr[17])

    def test_tube_inside_during_out_step_is_flagged(self):
        caps = _captures_from(self.f, lambda p, v: v)
        caps["out"][17] = (self.f["report"]["17"]["levels"]["entry"], 0.5)   # tube at entry
        res = regression.calibrate(self.f, caps)
        self.assertEqual(res["suspect"], [17])

    def test_normal_drift_not_flagged(self):
        # GPIO 6 drifts ±8 day to day (its whole signal) — not "suspect"
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: v + 8))
        self.assertEqual(res["suspect"], [])

    def test_out_only_is_offset(self):
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: v + 5, positions=("out",)))
        self.assertTrue(all(p["mode"] == "offset" for p in res["pins"].values()))

    def test_formula_text(self):
        res = regression.calibrate(self.f, _captures_from(self.f, lambda p, v: 0.9 * v + 12))
        self.assertIn("ADC = 0.90·F + 12", regression.formula(res["pins"][7]))


class UiSettingTest(unittest.TestCase):
    def test_default_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "app_settings.ini"
            with mock.patch.object(settings, "_PATH", path):
                self.assertEqual(settings.get_ui_version(), "v2")
                settings.set_ui_version("legacy")
                self.assertEqual(settings.get_ui_version(), "legacy")
                self.assertIn("version = legacy", path.read_text())
                settings.set_ui_version("v2")
                self.assertEqual(settings.get_ui_version(), "v2")

    def test_garbage_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "app_settings.ini"
            path.write_text("[ui]\nversion = banana\n")
            with mock.patch.object(settings, "_PATH", path):
                self.assertEqual(settings.get_ui_version(), "v2")


if __name__ == "__main__":
    unittest.main()
