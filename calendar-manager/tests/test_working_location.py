"""working_location.py: client-side refusals and relay payloads, with the relay stubbed.
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
ENV_KEYS = ("CALENDAR_MANAGER_NOW", "CALENDAR_MANAGER_CONFIG_JSON",
            "CALENDAR_MANAGER_WL_RELAY_URL", "CALENDAR_MANAGER_WL_RELAY_KEY")


class Stub:
    def __init__(self, reply=None, refuse=None):
        self.calls, self.reply, self.refuse = [], reply or {}, refuse

    def __call__(self, payload):
        self.calls.append(payload)
        if self.refuse:
            raise wl.Refused("relay: " + self.refuse)
        return dict(self.reply)


class WorkingLocationTest(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ENV_KEYS}
        os.environ["CALENDAR_MANAGER_NOW"] = NOW
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps(
            {"home_timezone": "America/New_York"})
        self.real = wl.relay

    def tearDown(self):
        wl.relay = self.real
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

    def test_set_relabels_through_relay(self):
        stub = wl.relay = Stub({"updated": {"id": "haj_20261002"}})
        code, out, err = self.run_cli("set", "--event-id", "haj_20261002", "--type", "custom",
                                      "--label", "MIT (E66, Cambridge)")
        self.assertEqual(code, 0, err)
        self.assertEqual(stub.calls, [{"op": "set", "eventId": "haj_20261002",
                                       "type": "custom", "label": "MIT (E66, Cambridge)"}])

    def test_set_retime_sends_offsets(self):
        stub = wl.relay = Stub({"updated": {}})
        code, _, err = self.run_cli("set", "--event-id", "p", "--type", "custom", "--label",
                                    "Babson Boston", "--start", "2026-10-02T16:30:00-04:00",
                                    "--end", "2026-10-02T18:00:00-04:00")
        self.assertEqual(code, 0, err)
        self.assertEqual(stub.calls[0]["start"], "2026-10-02T16:30:00-04:00")

    def test_relay_refusal_exits_2(self):
        wl.relay = Stub(refuse="event x is a default event, not a working location")
        code, _, err = self.run_cli("set", "--event-id", "x", "--type", "home")
        self.assertEqual(code, 2)
        self.assertIn("not a working location", err)

    def test_missing_relay_setup_is_a_clear_refusal(self):
        for k in ("CALENDAR_MANAGER_WL_RELAY_URL", "CALENDAR_MANAGER_WL_RELAY_KEY"):
            os.environ.pop(k, None)
        code, _, err = self.run_cli("list", "--date", "2026-10-02")
        self.assertEqual(code, 2)
        self.assertIn("relay isn't set up", err)

    def test_add_needs_offsets_and_future(self):
        stub = wl.relay = Stub()
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
        self.assertEqual(stub.calls, [])

    def test_add_all_day(self):
        stub = wl.relay = Stub({"created": {}})
        code, _, err = self.run_cli("add", "--type", "home", "--date", "2026-10-09")
        self.assertEqual(code, 0, err)
        self.assertEqual(stub.calls, [{"op": "add", "type": "home", "label": "",
                                       "date": "2026-10-09"}])

    def test_custom_and_office_need_a_label(self):
        stub = wl.relay = Stub()
        code, _, err = self.run_cli("add", "--type", "office", "--date", "2026-10-05")
        self.assertEqual(code, 2)
        self.assertIn("label", err)
        self.assertEqual(stub.calls, [])

    def test_kill_switch(self):
        os.environ["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps(
            {"working_location_relay": False})
        stub = wl.relay = Stub()
        code, _, _ = self.run_cli("list", "--date", "2026-10-02")
        self.assertEqual(code, 2)
        self.assertEqual(stub.calls, [])


if __name__ == "__main__":
    unittest.main()
