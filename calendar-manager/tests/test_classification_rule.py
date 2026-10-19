"""Every calendar-manager agent classifies through Clef, never a Claude model."""
import glob
import os
import re
import unittest

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
AGENTS = sorted(glob.glob(os.path.join(PLUGIN, "agents", "*.md")))


class ClassificationRuleTests(unittest.TestCase):
    def test_there_are_eight_agents(self):
        self.assertEqual(len(AGENTS), 8)

    def test_every_agent_carries_the_clef_rule(self):
        for path in AGENTS:
            text = open(path, encoding="utf-8").read()
            self.assertIn("## Classification (Clef only)", text, path)
            self.assertIn("references/classification.md", text, path)
            self.assertIn("clef", text.lower(), path)

    def test_no_agent_runs_on_haiku(self):
        for path in AGENTS:
            text = open(path, encoding="utf-8").read()
            self.assertIsNone(re.search(r"^model:\s*haiku\s*$", text, re.M), path)

    def test_every_question_bank_agent_is_in_the_bank(self):
        bank = open(os.path.join(PLUGIN, "skills", "calendar-sop", "references", "classification.md"),
                    encoding="utf-8").read()
        for path in AGENTS:
            name = os.path.basename(path)[:-3]
            self.assertIn(name, bank, "%s has no row in the question bank" % name)

    def test_run_skill_probes_clef_before_dispatching(self):
        run = open(os.path.join(PLUGIN, "skills", "run", "SKILL.md"), encoding="utf-8").read()
        self.assertIn("clef_ask.py\" --probe", run)
        self.assertLess(run.index("--probe"), run.index("4. **Dispatch agents**"))


if __name__ == "__main__":
    unittest.main()
