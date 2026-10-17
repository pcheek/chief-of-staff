"""Tests for skills/jet-lag-plan/scripts/jetlag_plan.py. Run: python3 -m unittest discover -s calendar-manager/tests"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "jet-lag-plan",
                      "scripts", "jetlag_plan.py")
NY, LON, DOH, SIN = "America/New_York", "Europe/London", "Asia/Qatar", "Asia/Singapore"


def plan(trip):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(trip, f)
    out = subprocess.run([sys.executable, SCRIPT, f.name], capture_output=True, text=True, timeout=30)
    os.unlink(f.name)
    return out.returncode, (json.loads(out.stdout) if out.returncode == 0 else out.stderr)


def utc(s):
    return dt.datetime.fromisoformat(s)


BOS_LHR = {"dest_tz": LON, "body_tz": NY, 
           "legs": [{"from": "BOS", "to": "LHR", "dep": "2026-11-02T21:55", "dep_tz": NY,
                     "arr": "2026-11-03T09:45", "arr_tz": LON}]}
BOS_SIN = {"dest_tz": SIN, "body_tz": NY, 
           "legs": [{"from": "BOS", "to": "DOH", "dep": "2026-11-02T22:10", "dep_tz": NY,
                     "arr": "2026-11-03T17:05", "arr_tz": DOH},
                    {"from": "DOH", "to": "SIN", "dep": "2026-11-04T01:30", "dep_tz": DOH,
                     "arr": "2026-11-04T15:00", "arr_tz": SIN}]}


class JetLagTest(unittest.TestCase):
    def test_flight_sleep_respects_takeoff_and_landing_margins(self):
        rc, d = plan(BOS_LHR)
        self.assertEqual(rc, 0)
        dep, arr = utc("2026-11-03T02:55:00+00:00"), utc("2026-11-03T09:45:00+00:00")
        sleeps = [e for e in d["events"] if e["kind"] == "sleep" and e["context"].startswith("flight")]
        self.assertTrue(sleeps)
        for e in sleeps:
            self.assertGreaterEqual(utc(e["start_utc"]), dep + dt.timedelta(minutes=30))
            self.assertLessEqual(utc(e["end_utc"]), arr - dt.timedelta(minutes=45))

    def test_layover_sleep_only_when_long_and_padded(self):
        rc, d = plan(BOS_SIN)
        self.assertEqual(rc, 0)
        land, dep = utc("2026-11-03T14:05:00+00:00"), utc("2026-11-03T22:30:00+00:00")
        lay = [e for e in d["events"] if e["kind"] == "sleep" and e["context"].startswith("layover")]
        self.assertEqual(len(lay), 1)
        self.assertGreaterEqual(utc(lay[0]["start_utc"]), land + dt.timedelta(minutes=30))
        self.assertLessEqual(utc(lay[0]["end_utc"]), dep - dt.timedelta(minutes=90))
        short = json.loads(json.dumps(BOS_SIN))
        short["legs"][1].update(dep="2026-11-03T21:00", arr="2026-11-04T10:30")
        _, d2 = plan(short)
        self.assertFalse([e for e in d2["events"] if e["kind"] == "sleep" and e["context"].startswith("layover")])

    def test_events_cover_only_the_flights_and_layovers(self):
        for trip in (BOS_LHR, BOS_SIN):
            _, d = plan(trip)
            first = utc(d["events"][0]["start_utc"])
            last = utc(d["events"][-1]["end_utc"])
            legs = trip["legs"]
            self.assertEqual(first.strftime("%Y-%m-%d %H:%M"),
                             dt.datetime.fromisoformat(legs[0]["dep"]).replace(tzinfo=ZoneInfo(legs[0]["dep_tz"]))
                             .astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
            self.assertEqual(last.strftime("%Y-%m-%d %H:%M"),
                             dt.datetime.fromisoformat(legs[-1]["arr"]).replace(tzinfo=ZoneInfo(legs[-1]["arr_tz"]))
                             .astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
            self.assertTrue(all(e["context"].startswith(("flight", "layover")) for e in d["events"]))

    def test_titles_and_minimum_length(self):
        _, d = plan(BOS_LHR)
        self.assertEqual({e["title"] for e in d["events"]},
                         {"Jet Lag - Sleep \U0001F634", "Jet Lag - Awake ☀️"})
        for e in d["events"]:
            self.assertGreaterEqual((utc(e["end_utc"]) - utc(e["start_utc"])).total_seconds(), 1800)

    def test_short_round_trip_plans_flight_sleep_only(self):
        rc, d = plan(dict(BOS_LHR, dest_tz=NY))
        self.assertEqual(rc, 0)
        self.assertEqual(d["mode"], "none")
        self.assertTrue(all(e["context"].startswith("flight") for e in d["events"]))

    def test_bad_input_exits_2(self):
        bad = json.loads(json.dumps(BOS_LHR))
        bad["legs"][0]["arr"] = "2026-11-02T20:00"
        self.assertEqual(plan(bad)[0], 2)


if __name__ == "__main__":
    unittest.main()
