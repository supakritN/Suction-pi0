import unittest

from app import display


class DetectTest(unittest.TestCase):
    def test_touch_display_2_is_baseline(self):
        p = display.detect(853, 480)
        self.assertEqual(p.name, "touch2-5in")
        self.assertEqual(p.scale, 1.0)

    def test_edatec_7in(self):
        p = display.detect(1024, 600)
        self.assertEqual(p.name, "edatec-7in")
        self.assertEqual(p.scale, 1.2)
        self.assertTrue(p.has_speaker)

    def test_portrait_orientation_matches_too(self):
        self.assertEqual(display.detect(600, 1024).name, "edatec-7in")

    def test_small_size_difference_still_matches(self):
        # panels/taskbars can shave a few pixels off what Tk reports
        self.assertEqual(display.detect(1020, 590).name, "edatec-7in")

    def test_unknown_screen_gets_fitted_scale(self):
        p = display.detect(1280, 800)
        self.assertEqual(p.name, "generic")
        self.assertAlmostEqual(p.scale, 1.5, places=2)   # min(1280/853, 800/480)

    def test_forced_profile(self):
        self.assertEqual(display.detect(1280, 800, profile="edatec-7in").name, "edatec-7in")

    def test_unknown_forced_profile_falls_back_to_auto(self):
        self.assertEqual(display.detect(853, 480, profile="nope").name, "touch2-5in")

    def test_scale_override_is_clamped(self):
        self.assertEqual(display.detect(853, 480, scale_override=1.3).scale, 1.3)
        self.assertEqual(display.detect(853, 480, scale_override=99).scale, display.MAX_SCALE)


if __name__ == "__main__":
    unittest.main()
