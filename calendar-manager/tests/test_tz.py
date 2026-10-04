"""Tests for scripts/tz.py. Run: python3 -m unittest discover -s calendar-manager/tests"""
import os
import subprocess
import sys
import unittest

TZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "tz.py")


def tz(*args):
    out = subprocess.run([sys.executable, TZ, *args], capture_output=True, text=True, timeout=20)
    return out.returncode, out.stdout.strip()


class TzTest(unittest.TestCase):
    def test_to_iso_uses_dst_correct_offset(self):
        self.assertEqual(tz("to-iso", "2026-07-01 14:00", "--zone", "America/New_York"),
                         (0, "2026-07-01T14:00:00-04:00"))
        self.assertEqual(tz("to-iso", "2026-12-01 14:00", "--zone", "America/New_York"),
                         (0, "2026-12-01T14:00:00-05:00"))

    def test_dst_gap_and_fold_refused(self):
        self.assertEqual(tz("to-iso", "2026-03-08 02:30", "--zone", "America/New_York")[0], 2)
        self.assertEqual(tz("to-iso", "2026-11-01 01:30", "--zone", "America/New_York")[0], 2)

    def test_us_europe_dst_mismatch_week(self):
        # Europe falls back Oct 25, the US on Nov 1: London is 4 hours ahead that week.
        self.assertEqual(tz("show", "2026-10-27T14:00:00+00:00", "--local", "Europe/London"),
                         (0, "Tue Oct 27, 2:00pm GMT (10:00am Boston)"))

    def test_show_at_home_has_no_boston_suffix(self):
        self.assertEqual(tz("show", "2026-10-05T13:00:00-04:00")[1], "Mon Oct 5, 1:00pm EDT")

    def test_check_flags_missing_offset(self):
        self.assertEqual(tz("check", "2026-10-05T13:00:00-04:00")[0], 0)
        self.assertEqual(tz("check", "2026-10-05T13:00:00")[0], 1)

    def test_day_window_is_local(self):
        self.assertEqual(tz("day-window", "--date", "2026-11-03", "--zone", "Asia/Tokyo")[1],
                         "2026-11-03T00:00:00+09:00 2026-11-04T00:00:00+09:00")

    def test_zone_of(self):
        self.assertEqual(tz("zone-of", "Aberdeen"), (0, "Europe/London"))
        self.assertEqual(tz("zone-of", "cambridge"), (0, "America/New_York"))
        self.assertEqual(tz("zone-of", "Santa Fe"), (0, "America/Denver"))
        self.assertEqual(tz("zone-of", "Albuquerque"), (0, "America/Denver"))
        self.assertEqual(tz("zone-of", "Atlantis")[0], 2)

    def test_bad_zone_names_rejected(self):
        self.assertNotEqual(tz("to-iso", "2026-10-05 13:00", "--zone", "EST")[0], 0)


if __name__ == "__main__":
    unittest.main()
