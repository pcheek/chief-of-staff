"""calendar_call.py: every time it emits carries an offset, and check catches the
mistakes the guard denies. Run: python3 -m unittest discover -s calendar-manager/tests"""
import contextlib
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import calendar_call as cc  # noqa: E402

NOW = "2026-10-03T12:00:00Z"
ENV = ("CALENDAR_MANAGER_NOW", "CALENDAR_MANAGER_CONFIG_JSON")


class CalendarCallTest(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ENV}
        os.environ["CALENDAR_MANAGER_NOW"] = NOW
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps(
            {"calendar_id": "paul@cheek.org", "home_timezone": "America/New_York"})

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_create_builds_offset_times_and_routing(self):
        code, out, err = self.run_cli("create", "--zone", "America/New_York",
                                      "--start", "2026-10-05 08:30", "--end", "2026-10-05 09:00",
                                      "--summary", "HOLD: offered to Bob Toohey", "--color", "11",
                                      "--busy")
        self.assertEqual(code, 0, err)
        body = json.loads(out)
        self.assertEqual(body["startTime"], "2026-10-05T08:30:00-04:00")
        self.assertEqual(body["endTime"], "2026-10-05T09:00:00-04:00")
        self.assertEqual(body["calendarId"], "paul@cheek.org")
        self.assertEqual(body["availability"], "AVAILABILITY_BUSY")
        self.assertEqual(body["notificationLevel"], "NONE")

    def test_dst_and_foreign_zone_offsets(self):
        code, out, _ = self.run_cli("times", "--zone", "America/New_York",
                                    "--start", "2026-11-02 09:00", "--end", "2026-11-02 10:00")
        self.assertEqual(json.loads(out)["startTime"], "2026-11-02T09:00:00-05:00")
        code, out, _ = self.run_cli("times", "--zone", "Asia/Singapore",
                                    "--start", "2026-10-11 00:00", "--end", "2026-10-11 00:20")
        self.assertEqual(json.loads(out)["startTime"], "2026-10-11T00:00:00+08:00")

    def test_check_catches_the_naive_time_the_guard_denied(self):
        bad = {"calendarId": "paul@cheek.org", "summary": "HOLD",
               "startTime": "2026-10-05T08:30:00", "endTime": "2026-10-05T09:00:00"}
        code, _, err = self.run_cli("check", json.dumps(bad))
        self.assertEqual(code, 2)
        self.assertIn("has no UTC offset", err)
        self.assertIn("calendar_call.py times", err)

    def test_check_passes_a_built_call(self):
        _, out, _ = self.run_cli("create", "--zone", "America/New_York", "--start",
                                 "2026-10-08 15:30", "--end", "2026-10-08 17:30",
                                 "--summary", "HOLD", "--busy")
        code, ok, err = self.run_cli("check", out)
        self.assertEqual(code, 0, err)
        self.assertEqual(ok.strip(), "ok")

    def test_check_other_mistakes(self):
        cases = [
            ({"calendarId": "primary", "startTime": "2026-10-05T08:30:00-04:00",
              "endTime": "2026-10-05T09:00:00-04:00"}, "calendarId must be"),
            ({"calendarId": "paul@cheek.org", "startTime": "2026-10-05T09:00:00-04:00",
              "endTime": "2026-10-05T08:30:00-04:00"}, "not after"),
            ({"calendarId": "paul@cheek.org", "startTime": "2026-10-02T09:30:00-04:00",
              "endTime": "2026-10-02T10:00:00-04:00"}, "in the past"),
            ({"calendarId": "paul@cheek.org", "timeZone": "Europe/London",
              "startTime": "2026-10-05T08:30:00-04:00",
              "endTime": "2026-10-05T09:00:00-04:00"}, "disagrees with timeZone"),
        ]
        for body, want in cases:
            code, _, err = self.run_cli("check", json.dumps(body))
            self.assertEqual(code, 2, body)
            self.assertIn(want, err)

    def test_check_a_list_of_calls(self):
        calls = [{"calendarId": "paul@cheek.org", "startTime": "2026-10-08T15:30:00-04:00",
                  "endTime": "2026-10-08T17:30:00-04:00"},
                 {"calendarId": "paul@cheek.org", "startTime": "2026-10-09T09:00:00",
                  "endTime": "2026-10-09T10:30:00"}]
        code, _, err = self.run_cli("check", json.dumps(calls))
        self.assertEqual(code, 2)
        self.assertIn("call 2:", err)
        self.assertNotIn("call 1:", err)

    def test_all_day_and_refusals(self):
        code, out, err = self.run_cli("create", "--all-day", "--start", "2026-10-11",
                                      "--end", "2026-10-12", "--summary", "NOTE", "--free")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["allDay"])
        code, _, err = self.run_cli("times", "--start", "2026-10-05 08:30", "--end",
                                    "2026-10-05 09:00")
        self.assertEqual(code, 2)
        self.assertIn("--zone is required", err)
        code, _, err = self.run_cli("times", "--zone", "EST", "--start", "2026-10-05 08:30",
                                    "--end", "2026-10-05 09:00")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
