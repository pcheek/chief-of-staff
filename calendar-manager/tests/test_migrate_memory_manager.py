"""scripts/migrate_to_memory_manager.py on a throwaway clone."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import migrate_to_memory_manager as m  # noqa: E402


def git(d, *a):
    subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True,
                   capture_output=True)


class Migrate(unittest.TestCase):
    def make(self, moved=True):
        tmp = tempfile.mkdtemp()
        git(tmp, "init", "-q", "-b", "main")
        open(os.path.join(tmp, ".calendar-manager-memory"), "w").close()
        open(os.path.join(tmp, ".gitattributes"), "w").write("guidance.json merge=calendar-guidance\n")
        if moved:
            os.makedirs(os.path.join(tmp, "calendar"))
            open(os.path.join(tmp, "calendar", "guidance.json"), "w").write("{}")
        else:
            open(os.path.join(tmp, "guidance.json"), "w").write("{}")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "x")
        return tmp

    def test_refuses_before_the_data_move(self):
        self.assertTrue(any("data-move" in p for p in m.migrate(self.make(moved=False))))

    def test_refuses_dirty_tree(self):
        tmp = self.make()
        open(os.path.join(tmp, "stray"), "w").write("x")
        self.assertIn("working tree is not clean", m.migrate(tmp))

    def test_dry_run_changes_nothing(self):
        tmp = self.make()
        self.assertEqual(m.migrate(tmp, dry_run=True), [])
        self.assertTrue(os.path.isfile(os.path.join(tmp, ".calendar-manager-memory")))

    def test_swaps_marker_and_attributes(self):
        tmp = self.make()
        problems = m.migrate(tmp)
        # vendor_to_memory needs the real plugin tree, which this checkout has
        self.assertEqual(problems, [])
        self.assertTrue(os.path.isfile(os.path.join(tmp, ".memory-manager")))
        self.assertFalse(os.path.exists(os.path.join(tmp, ".calendar-manager-memory")))
        self.assertIn("calendar/guidance.json merge=calendar-guidance",
                      open(os.path.join(tmp, ".gitattributes")).read())
        self.assertTrue(os.path.isfile(os.path.join(tmp, ".claude", "settings.json")))


if __name__ == "__main__":
    unittest.main()
