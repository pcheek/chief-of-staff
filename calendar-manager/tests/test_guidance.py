"""Tests for scripts/guidance.py. Run: python3 -m unittest discover -s calendar-manager/tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDANCE = os.path.join(HERE, "..", "scripts", "guidance.py")


class GuidanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, CALENDAR_MANAGER_HOME=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def g(self, *args):
        out = subprocess.run([sys.executable, GUIDANCE, *args], capture_output=True,
                             text=True, env=self.env, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def data(self):
        with open(os.path.join(self.tmp.name, "guidance.json")) as fh:
            return json.load(fh)

    def test_init_is_idempotent(self):
        self.g("init")
        n = len(self.data()["questions"])
        self.g("init")
        self.assertEqual(len(self.data()["questions"]), n)

    def test_answered_seed_is_not_reasked(self):
        self.g("init")
        self.g("answer", "Q1", "--answer", "red", "--rule", "Notes are red.")
        self.g("init")
        open_qs = json.loads(self.g("open", "--json"))
        self.assertNotIn("Q1", [q["id"] for q in open_qs])

    def test_v01_install_gets_only_new_seeds(self):
        # A real v0.1 guidance.json: its five seeds, a single "seeded" flag, no seeded_keys.
        v01 = [
            "Notes and holds: the 2024 calendar doc says purple, the Apr 2025 SOP says red "
            "(Tomato). Which color marks a note that needs your review?",
            "Airport transit: the SOP's flight steps say purple, its color legend says lavender "
            "for travel. Which color for driving to the airport?",
            "The 1:1 roster in the calendar doc is the MIT Trust Center team from 2024. Which of "
            "those 1:1s still exist, and who is on your current roster with what cadence?",
            "Which days and where do you commute now (the doc assumes MIT, 45 minutes, blocked "
            "as one hour)? Is Friday still the standard work-from-home day?",
            "Which email is the calendar these runs manage (paul@cheek.org or pcheek@mit.edu)? "
            "If it differs from config.json owner_emails, edit ~/.claude/calendar-manager/"
            "config.json yourself: the agents are not allowed to.",
        ]
        d = {"rules": [], "seeded": "2026-10-01T00:00:00-04:00",
             "questions": [{"id": "Q%d" % (i + 1), "agent": "x", "question": q,
                            "status": "open", "created": "2026-10-01", "last_asked": "",
                            "times_asked": 1, "events": []} for i, q in enumerate(v01)]}
        with open(os.path.join(self.tmp.name, "guidance.json"), "w") as fh:
            json.dump(d, fh)
        self.g("init")
        qs = self.data()["questions"]
        added = [q["question"] for q in qs[5:]]
        self.assertEqual(len(added), 2, added)  # time zone + who schedules for you
        self.assertTrue(any("time zone" in q for q in added))
        self.assertTrue(any("schedules on your behalf" in q for q in added))

    def test_fresh_install_never_asks_the_retired_notes_color(self):
        self.g("init")
        texts = [q["question"] for q in self.data()["questions"]]
        self.assertEqual(len(texts), 6)
        self.assertFalse([t for t in texts if t.startswith("Notes and holds")])

    def test_duplicate_question_is_merged(self):
        self.g("ask", "--agent", "a", "--question", "Overlap Tue 2pm?")
        out = self.g("ask", "--agent", "a", "--question", "overlap tue 2pm")
        self.assertIn("already open", out)

    def test_rule_lifecycle(self):
        self.g("add-rule", "--rule", "Release holds after 5 days.", "--scope",
               "offered-times-tracker")
        self.g("tick")
        self.g("tick")
        self.assertEqual(len(json.loads(self.g("candidates"))), 1)
        self.g("supersede", "G1", "--rule", "Release holds after 3 days.")
        rules = json.loads(self.g("rules", "--json"))
        self.assertEqual([r["id"] for r in rules], ["G2"])
        md = open(os.path.join(self.tmp.name, "guidance.md")).read()
        self.assertIn("3 days", md)
        self.assertNotIn("5 days", md)

    def test_instruction_source_is_recorded(self):
        self.g("add-rule", "--rule", "No meetings before 10am after a red-eye.",
               "--source", "instruction:i_20261005T141601_o5e6")
        self.g("supersede", "G1", "--rule", "No meetings before 10:30am after a red-eye.",
               "--source", "instruction:i_20261006T090000_ab12")
        rules = {r["id"]: r for r in self.data()["rules"]}
        self.assertEqual(rules["G1"]["source"], "instruction:i_20261005T141601_o5e6")
        self.assertEqual(rules["G2"]["source"],
                         "instruction:i_20261006T090000_ab12, correcting G1")
        self.assertEqual(rules["G1"]["status"], "superseded")


if __name__ == "__main__":
    unittest.main()
