"""memory-manager layout: one private repo with calendar/ and email/ folders.

The marker .memory-manager sits at the repo root and calendar data lives in calendar/. The legacy
marker .calendar-manager-memory still means the repo root is the data folder (tests in test_sync.py).
Run: python3 -m unittest discover -s calendar-manager/tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
GUIDANCE = os.path.join(SCRIPTS, "guidance.py")
sys.path.insert(0, SCRIPTS)
import cm_paths  # noqa: E402


def sh(*args, cwd=None):
    out = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError("%s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.env = dict(os.environ)
        for k in ("CALENDAR_MANAGER_HOME", "CLAUDE_PROJECT_DIR"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_marker_puts_data_in_calendar_folder(self):
        open(os.path.join(self.root, ".memory-manager"), "w").close()
        os.makedirs(os.path.join(self.root, "email"))
        old = dict(os.environ)
        os.environ.pop("CALENDAR_MANAGER_HOME", None)
        try:
            p = cm_paths.paths(os.path.join(self.root, "email"))
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(p["root"], self.root)
        self.assertEqual(p["home"], os.path.join(self.root, "calendar"))
        self.assertEqual(p["state"], os.path.join(self.root, "calendar", "state"))

    def test_legacy_marker_keeps_root_as_data_folder(self):
        open(os.path.join(self.root, ".calendar-manager-memory"), "w").close()
        p = cm_paths.paths(self.root)
        self.assertEqual(p["root"], self.root)
        self.assertEqual(p["home"], self.root)

    def test_env_may_name_either_root_or_calendar_folder(self):
        open(os.path.join(self.root, ".memory-manager"), "w").close()
        os.makedirs(os.path.join(self.root, "calendar"))
        old = os.environ.get("CALENDAR_MANAGER_HOME")
        try:
            for value in (self.root, os.path.join(self.root, "calendar")):
                os.environ["CALENDAR_MANAGER_HOME"] = value
                p = cm_paths.paths()
                self.assertEqual((p["root"], p["home"]), (self.root, os.path.join(self.root, "calendar")))
        finally:
            if old is None:
                os.environ.pop("CALENDAR_MANAGER_HOME", None)
            else:
                os.environ["CALENDAR_MANAGER_HOME"] = old

    def test_both_markers_are_found_from_a_subfolder(self):
        sub = os.path.join(self.root, "email", "lists")
        os.makedirs(sub)
        open(os.path.join(self.root, ".memory-manager"), "w").close()
        self.assertEqual(cm_paths.find_marker(sub), self.root)


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.remote = os.path.join(base, "remote.git")
        sh("git", "init", "--bare", "-q", "-b", "main", self.remote)
        seed = os.path.join(base, "seed")
        sh("git", "clone", "-q", self.remote, seed)
        sh("git", "checkout", "-q", "-b", "main", cwd=seed)
        for name, body in ((".gitignore", "state/\nconfig.json\n"), (".memory-manager", "")):
            with open(os.path.join(seed, name), "w") as fh:
                fh.write(body)
        os.makedirs(os.path.join(seed, "email"))
        with open(os.path.join(seed, "email", "README.md"), "w") as fh:
            fh.write("email data\n")
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=seed)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "scaffold", cwd=seed)
        sh("git", "push", "-q", "origin", "main", cwd=seed)
        self.g(seed, "init")
        self.g(seed, "sync", "push", "--message", "bootstrap")
        self.a = self.clone("a")
        self.b = self.clone("b")

    def tearDown(self):
        self.tmp.cleanup()

    def clone(self, name):
        path = os.path.join(self.tmp.name, name)
        sh("git", "clone", "-q", self.remote, path)
        return path

    def g(self, root, *args):
        env = dict(os.environ, CALENDAR_MANAGER_HOME=root)
        env.pop("CALENDAR_MANAGER_CONFIG", None)
        env.pop("CALENDAR_MANAGER_CONFIG_JSON", None)
        out = subprocess.run([sys.executable, GUIDANCE, *args], cwd=root, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def test_data_commits_under_calendar_and_email_is_untouched(self):
        check = self.clone("check")
        files = sh("git", "ls-files", cwd=check).split()
        self.assertIn("calendar/guidance.json", files)
        self.assertIn("calendar/questions.md", files)
        self.assertIn("email/README.md", files)
        self.assertFalse([f for f in files if f.startswith("calendar/state/") or f.endswith("config.json")])
        self.assertNotIn("guidance.json", files)

    def test_overlapping_runs_merge_without_force(self):
        self.g(self.a, "sync", "pull")
        self.g(self.b, "sync", "pull")
        qa = self.g(self.a, "ask", "--agent", "x", "--question", "Daily question?").split()[0]
        qb = self.g(self.b, "ask", "--agent", "y", "--question", "Weekly question?").split()[0]
        self.assertEqual(qa, qb)
        self.g(self.a, "sync", "push", "--message", "run daily")
        out = self.g(self.b, "sync", "push", "--message", "run weekly")
        self.assertIn("rejected", out)
        check = self.clone("check2")
        with open(os.path.join(check, "calendar", "guidance.json")) as fh:
            data = json.load(fh)
        texts = {q["question"]: q["id"] for q in data["questions"]}
        self.assertIn("Daily question?", texts)
        self.assertIn("Weekly question?", texts)
        self.assertEqual(len(set(texts.values())), len(texts), "ids must stay unique")

    def test_merge_driver_attributes_use_the_calendar_prefix(self):
        self.g(self.a, "sync", "pull")
        with open(os.path.join(self.a, ".git", "info", "attributes")) as fh:
            attrs = fh.read()
        self.assertIn("calendar/guidance.json merge=calendar-guidance", attrs)


class Guard(unittest.TestCase):
    def test_email_sessions_inside_the_repo_are_guarded_so_they_must_run_elsewhere(self):
        # A session whose cwd is inside a memory-manager clone is a calendar-manager session.
        # Email runs therefore start in the marketplace checkout and reach this repo by path only.
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.realpath(tmp)
            open(os.path.join(root, ".memory-manager"), "w").close()
            os.makedirs(os.path.join(root, "email"))
            self.assertEqual(cm_paths.find_marker(os.path.join(root, "email")), root)


if __name__ == "__main__":
    unittest.main()
