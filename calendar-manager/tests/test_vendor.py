"""scripts/vendor_to_memory.py: the copy cloud routines load from the memory repo.
Run: python3 -m unittest discover -s calendar-manager/tests"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "..", "..", "scripts", "vendor_to_memory.py")


class VendorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = self.tmp.name
        open(os.path.join(self.mem, ".calendar-manager-memory"), "w").close()
        os.makedirs(os.path.join(self.mem, ".claude"))
        with open(os.path.join(self.mem, ".claude", "settings.json"), "w") as fh:
            json.dump({"permissions": {"deny": ["Bash(rm -rf:*)"]}}, fh)
        self.vendor()

    def tearDown(self):
        self.tmp.cleanup()

    def vendor(self):
        out = subprocess.run([sys.executable, VENDOR, self.mem], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def claude(self, *parts):
        return os.path.join(self.mem, ".claude", *parts)

    def test_settings_hooks_and_kept_keys(self):
        with open(self.claude("settings.json")) as fh:
            s = json.load(fh)
        self.assertEqual(s["permissions"]["deny"], ["Bash(rm -rf:*)"])
        for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
            cmd = s["hooks"][event][0]["hooks"][0]["command"]
            self.assertIn("$CLAUDE_PROJECT_DIR/.claude/calendar-manager/scripts/guard.py", cmd)

    def test_skills_renamed_and_rewritten(self):
        names = sorted(os.path.basename(os.path.dirname(p))
                       for p in glob.glob(self.claude("skills", "*", "SKILL.md")))
        self.assertEqual(names, ["calendar-guidance", "calendar-promote-guidance", "calendar-run",
                                 "calendar-schedule", "calendar-sop"])
        for p in glob.glob(self.claude("skills", "*", "SKILL.md")):
            with open(p) as fh:
                body = fh.read()
            self.assertRegex(body, r"(?m)^name: %s$" % re.escape(os.path.basename(os.path.dirname(p))))

    def test_no_plugin_only_references_left(self):
        for p in glob.glob(self.claude("**", "*"), recursive=True):
            if os.path.isfile(p) and p.endswith((".md", ".json")):
                with open(p) as fh:
                    body = fh.read()
                self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", body, p)
                self.assertNotIn("/calendar-manager:", body, p)

    def test_agents_and_stamp(self):
        agents = sorted(os.listdir(self.claude("agents")))
        self.assertEqual(len(agents), 8)
        with open(self.claude("calendar-manager", "VENDORED.json")) as fh:
            stamp = json.load(fh)
        self.assertIn("/calendar-run", stamp["skills"])
        self.assertTrue(stamp["source"].startswith("pcheek/chief-of-staff@"))

    def test_vendored_guard_works_and_guards_the_repo(self):
        guard = self.claude("calendar-manager", "scripts", "guard.py")
        env = dict(os.environ)
        env.pop("CALENDAR_MANAGER_HOME", None)
        ev = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": self.mem,
              "tool_name": "mcp__Google_Calendar__delete_event", "tool_input": {"eventId": "x"}}
        out = subprocess.run([sys.executable, guard], input=json.dumps(ev), text=True,
                             capture_output=True, env=env)
        self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"],
                         "deny")

    def snapshot(self):
        out = {}
        for p in glob.glob(self.claude("**", "*"), recursive=True):
            if os.path.isfile(p) and not p.endswith("VENDORED.json"):
                with open(p, "rb") as fh:
                    out[p] = fh.read()
        return out

    def test_idempotent(self):
        before = self.snapshot()
        self.vendor()
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
