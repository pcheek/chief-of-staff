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
        # A v0.1 install: five seeds, a single "seeded" flag, no seeded_keys.
        self.g("init")
        d = self.data()
        d.pop("seeded_keys")
        d["questions"] = d["questions"][:5]
        d["questions"][0]["status"] = "answered"
        with open(os.path.join(self.tmp.name, "guidance.json"), "w") as fh:
            json.dump(d, fh)
        self.g("init")
        qs = self.data()["questions"]
        # The answered v0.1 question stays answered; every later seed arrives exactly once.
        self.assertEqual(len(qs), 5 + 2)
        self.assertEqual(sum(q["status"] == "open" for q in qs), 4 + 2)

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


if __name__ == "__main__":
    unittest.main()
