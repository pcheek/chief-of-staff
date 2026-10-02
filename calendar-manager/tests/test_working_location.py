"""working_location.py: refusals and request bodies, with the HTTP layer stubbed out.
Run: python3 -m unittest discover -s calendar-manager/tests"""
import contextlib
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import working_location as wl  # noqa: E402

NOW = "2026-10-02T12:45:00Z"  # 8:45am Boston
CFG = json.dumps({"calendar_id": "paul@cheek.org", "home_timezone": "America/New_York"})


def home_instance(day="2026-10-02"):
    return {"id": "haj_20261002", "eventType": "workingLocation",
            "recurringEventId": "haj", "start": {"date": day}, "end": {"date": "2026-10-03"},
            "workingLocationProperties": {"type": "homeOffice", "homeOffice": {}}}


class Stub:
    def __init__(self, get=None):
        self.calls, self.get = [], get or {}

    def __call__(self, method, path, body=None, query=None):
        self.calls.append((method, path, body, query))
        if method == "GET":
            return self.get
        return dict(body or {}, id="new1")


class WorkingLocationTest(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in
                    ("CALENDAR_MANAGER_NOW", "CALENDAR_MANAGER_CONFIG_JSON")}
        os.environ["CALENDAR_MANAGER_NOW"] = NOW
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = CFG
        self.real = wl.request

    def tearDown(self):
        wl.request = self.real
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wl.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_set_retypes_todays_all_day_home(self):
        stub = wl.request = Stub(home_instance())
        code, out, err = self.run_cli("set", "--event-id", "haj_20261002", "--type", "custom",
                                      "--label", "MIT (E66, Cambridge)")
        self.assertEqual(code, 0, err)
        method, path, body, query = stub.calls[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/calendars/paul%40cheek.org/events/haj_20261002")
        self.assertEqual(body["workingLocationProperties"],
                         {"type": "customLocation",
                          "customLocation": {"label": "MIT (E66, Cambridge)"}})
        self.assertEqual(query, {"sendUpdates": "none"})
        self.assertEqual(set(body), {"workingLocationProperties", "summary"})

    def test_set_refuses_non_working_location(self):
        stub = wl.request = Stub({"id": "x", "eventType": "default",
                                  "start": {"dateTime": "2026-10-02T18:00:00-04:00"}})
        code, _, err = self.run_cli("set", "--event-id", "x", "--type", "home")
        self.assertEqual(code, 2)
        self.assertIn("not a working location", err)
        self.assertEqual([c[0] for c in stub.calls], ["GET"])

    def test_set_refuses_started_partial_day(self):
        wl.request = Stub({"id": "p", "eventType": "workingLocation",
                           "start": {"dateTime": "2026-10-02T08:00:00-04:00"},
                           "end": {"dateTime": "2026-10-02T15:00:00-04:00"}})
        code, _, err = self.run_cli("set", "--event-id", "p", "--type", "home")
        self.assertEqual(code, 2)
        self.assertIn("started", err)

    def test_set_refuses_past_all_day(self):
        wl.request = Stub(home_instance("2026-10-01") | {"end": {"date": "2026-10-02"}})
        code, _, err = self.run_cli("set", "--event-id", "h", "--type", "home")
        self.assertEqual(code, 2)
        self.assertIn("ended", err)

    def test_set_moves_future_partial_day(self):
        stub = wl.request = Stub({"id": "p", "eventType": "workingLocation",
                                  "start": {"dateTime": "2026-10-02T16:15:00-04:00"},
                                  "end": {"dateTime": "2026-10-02T18:00:00-04:00"}})
        code, _, err = self.run_cli("set", "--event-id", "p", "--type", "custom", "--label",
                                    "Babson Boston", "--start", "2026-10-02T16:30:00-04:00",
                                    "--end", "2026-10-02T18:00:00-04:00")
        self.assertEqual(code, 0, err)
        self.assertEqual(stub.calls[-1][2]["start"], {"dateTime": "2026-10-02T16:30:00-04:00"})

    def test_add_partial_day_needs_offsets_and_future(self):
        wl.request = Stub()
        code, _, err = self.run_cli("add", "--type", "custom", "--label", "MIT",
                                    "--start", "2026-10-03T09:00:00", "--end",
                                    "2026-10-03T10:00:00")
        self.assertEqual(code, 2)
        self.assertIn("offset", err)
        code, _, err = self.run_cli("add", "--type", "custom", "--label", "MIT",
                                    "--start", "2026-10-02T07:00:00-04:00", "--end",
                                    "2026-10-02T10:00:00-04:00")
        self.assertEqual(code, 2)
        self.assertIn("past", err)

    def test_add_marks_agent_and_sends_no_updates(self):
        stub = wl.request = Stub()
        code, _, err = self.run_cli("add", "--type", "office", "--label", "MIT E66",
                                    "--start", "2026-10-05T09:00:00-04:00", "--end",
                                    "2026-10-05T17:00:00-04:00")
        self.assertEqual(code, 0, err)
        method, path, body, query = stub.calls[-1]
        self.assertEqual((method, path), ("POST", "/calendars/paul%40cheek.org/events"))
        self.assertEqual(body["eventType"], "workingLocation")
        self.assertEqual(body["extendedProperties"], {"private": {"calendarManager": "agent"}})
        self.assertNotIn("attendees", body)
        self.assertEqual(query, {"sendUpdates": "none"})

    def test_custom_and_office_need_a_label(self):
        wl.request = Stub()
        code, _, err = self.run_cli("add", "--type", "custom", "--date", "2026-10-05")
        self.assertEqual(code, 2)
        self.assertIn("label", err)

    def test_kill_switch(self):
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps(
            {"calendar_id": "paul@cheek.org", "working_location_rest": False})
        stub = wl.request = Stub()
        code, _, err = self.run_cli("list", "--date", "2026-10-02")
        self.assertEqual(code, 2)
        self.assertEqual(stub.calls, [])


if __name__ == "__main__":
    unittest.main()
