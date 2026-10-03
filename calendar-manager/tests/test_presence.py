"""presence.py: OOO nights for stays in other time zones.
Run: python3 -m unittest discover -s calendar-manager/tests"""
import contextlib
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import presence  # noqa: E402

ENV = ("CALENDAR_MANAGER_NOW", "CALENDAR_MANAGER_CONFIG_JSON")


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ENV}
        os.environ["CALENDAR_MANAGER_NOW"] = "2026-10-03T12:00:00Z"
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps({"calendar_id": "paul@cheek.org"})

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def ooo(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            code = presence.main(["ooo", *argv])
        return code, (json.loads(out.getvalue()) if code == 0 else None)

    def test_singapore_stay(self):
        code, out = self.ooo("--zone", "Asia/Singapore", "--city", "Singapore",
                             "--from", "2026-10-10", "--to", "2026-10-18",
                             "--arrive", "2026-10-11T00:20:00+08:00",
                             "--depart", "2026-10-17T21:00:00+08:00",
                             "--skip", "2026-10-12T18:00:00+08:00/2026-10-13T08:00:00+08:00")
        self.assertEqual(code, 0)
        spans = [(b["startTime"], b["endTime"]) for b in out]
        self.assertEqual(spans[0], ("2026-10-11T00:20:00+08:00", "2026-10-11T07:00:00+08:00"))
        self.assertIn(("2026-10-11T20:00:00+08:00", "2026-10-12T07:00:00+08:00"), spans)
        self.assertNotIn(("2026-10-12T20:00:00+08:00", "2026-10-13T07:00:00+08:00"), spans)
        self.assertEqual(spans[-1], ("2026-10-17T20:00:00+08:00", "2026-10-17T21:00:00+08:00"))
        for b in out:
            self.assertEqual(b["eventType"], "OUT_OF_OFFICE")
            self.assertEqual(b["calendarId"], "paul@cheek.org")
            self.assertEqual(b["summary"], "OOO: Singapore night (8pm to 7am local)")

    def test_partial_skip_leaves_the_rest(self):
        code, out = self.ooo("--zone", "Europe/London", "--from", "2026-11-02", "--to", "2026-11-03",
                             "--skip", "2026-11-02T20:00:00+00:00/2026-11-02T23:00:00+00:00")
        self.assertEqual(code, 0)
        self.assertEqual([(b["startTime"], b["endTime"]) for b in out],
                         [("2026-11-02T23:00:00+00:00", "2026-11-03T07:00:00+00:00")])

    def test_same_clock_as_boston_gets_none(self):
        code, out = self.ooo("--zone", "America/New_York", "--from", "2026-10-07", "--to", "2026-10-09")
        self.assertEqual((code, out), (0, []))
        code, out = self.ooo("--zone", "America/Toronto", "--from", "2026-10-07", "--to", "2026-10-09")
        self.assertEqual((code, out), (0, []))

    def test_dst_night_keeps_local_wall_times(self):
        # London leaves summer time on 2026-10-25: the night still runs 20:00 to 07:00 local.
        code, out = self.ooo("--zone", "Europe/London", "--from", "2026-10-24", "--to", "2026-10-25")
        self.assertEqual(code, 0)
        self.assertEqual((out[0]["startTime"], out[0]["endTime"]),
                         ("2026-10-24T20:00:00+01:00", "2026-10-25T07:00:00+00:00"))

    def test_past_nights_dropped_and_current_trimmed(self):
        os.environ["CALENDAR_MANAGER_NOW"] = "2026-10-11T15:00:00Z"  # 23:00 in Singapore
        code, out = self.ooo("--zone", "Asia/Singapore", "--from", "2026-10-10", "--to", "2026-10-12")
        self.assertEqual(code, 0)
        self.assertEqual((out[0]["startTime"], out[0]["endTime"]),
                         ("2026-10-11T23:00:00+08:00", "2026-10-12T07:00:00+08:00"))
        self.assertEqual(len(out), 1)

    def test_refusals(self):
        self.assertEqual(self.ooo("--zone", "Asia/Singapore", "--from", "2026-10-12",
                                  "--to", "2026-10-10")[0], 2)
        self.assertEqual(self.ooo("--zone", "Asia/Singapore", "--from", "2026-10-10",
                                  "--to", "2026-10-12", "--arrive", "2026-10-11T00:20")[0], 2)
        self.assertEqual(self.ooo("--zone", "SGT", "--from", "2026-10-10", "--to", "2026-10-12")[0], 2)


if __name__ == "__main__":
    unittest.main()
