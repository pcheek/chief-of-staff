"""Memory-repo sync: two clones of one bare remote stand in for overlapping cloud runs.
Run: python3 -m unittest discover -s calendar-manager/tests"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDANCE = os.path.join(HERE, "..", "scripts", "guidance.py")
GITIGNORE = "state/\nconfig.json\n"
GITATTRIBUTES = ("guidance.json merge=calendar-guidance\n"
                 "guidance.md merge=calendar-render\n"
                 "questions.md merge=calendar-render\n")


def sh(*args, cwd=None):
    out = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError("%s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.remote = os.path.join(root, "remote.git")
        sh("git", "init", "--bare", "-q", "-b", "main", self.remote)
        seed = os.path.join(root, "seed")
        sh("git", "clone", "-q", self.remote, seed)
        sh("git", "checkout", "-q", "-b", "main", cwd=seed)
        for name, body in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES),
                           (".calendar-manager-memory", "")):
            with open(os.path.join(seed, name), "w") as fh:
                fh.write(body)
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

    def g(self, home, *args):
        env = dict(os.environ, CALENDAR_MANAGER_HOME=home)
        env.pop("CALENDAR_MANAGER_CONFIG", None)
        env.pop("CALENDAR_MANAGER_CONFIG_JSON", None)
        out = subprocess.run([sys.executable, GUIDANCE, *args], cwd=home, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def remote_data(self):
        check = self.clone("check-%d" % len(os.listdir(self.tmp.name)))
        with open(os.path.join(check, "guidance.json")) as fh:
            return json.load(fh), sh("git", "ls-files", cwd=check).split(), \
                sh("git", "log", "--format=%s", cwd=check).split("\n")

    def test_bootstrap_commits_data_only(self):
        _, files, _ = self.remote_data()
        self.assertIn("guidance.json", files)
        self.assertIn("questions.md", files)
        self.assertFalse([f for f in files if f.startswith("state/") or f == "config.json"])

    def test_overlapping_runs_both_land_without_force(self):
        self.g(self.a, "sync", "pull")
        self.g(self.b, "sync", "pull")
        qa = self.g(self.a, "ask", "--agent", "x", "--question", "Daily question?").split()[0]
        qb = self.g(self.b, "ask", "--agent", "y", "--question", "Weekly question?").split()[0]
        self.assertEqual(qa, qb)  # both runs picked the same next id
        self.g(self.a, "sync", "push", "--message", "run 2026-10-05 daily")
        out = self.g(self.b, "sync", "push", "--message", "run 2026-10-04 weekly")
        self.assertIn("rejected", out)
        data, files, log = self.remote_data()
        texts = {q["question"]: q["id"] for q in data["questions"]}
        self.assertIn("Daily question?", texts)
        self.assertIn("Weekly question?", texts)
        self.assertEqual(len(set(texts.values())), len(texts), "ids must stay unique")
        self.assertIn("run 2026-10-05 daily", log)
        self.assertTrue(any(s.startswith("run 2026-10-04 weekly") for s in log))
        with open(os.path.join(self.b, "questions.md")) as fh:
            md = fh.read()
        self.assertIn("Daily question?", md)
        self.assertIn("Weekly question?", md)

    def test_session_branch_still_syncs_main(self):
        # A cloud session checks out its own claude/<name> branch; memory must still
        # land on main, and that session must still see what other runs pushed to main.
        sh("git", "checkout", "-q", "-b", "claude/some-session", cwd=self.a)
        self.g(self.b, "ask", "--agent", "y", "--question", "Pushed by B?")
        self.g(self.b, "sync", "push", "--message", "b")
        out = self.g(self.a, "sync", "pull")
        self.assertIn("origin/main", out)
        self.g(self.a, "ask", "--agent", "x", "--question", "From the session branch?")
        out = self.g(self.a, "sync", "push", "--message", "session run")
        self.assertIn("origin/main", out)
        data, _, log = self.remote_data()
        texts = {q["question"] for q in data["questions"]}
        self.assertIn("From the session branch?", texts)
        self.assertIn("Pushed by B?", texts)
        self.assertIn("session run", log)
        heads = sh("git", "ls-remote", "--heads", self.remote)
        self.assertNotIn("claude/some-session", heads)

    def test_same_question_from_both_runs_merges(self):
        self.g(self.a, "ask", "--agent", "x", "--question", "Shared question?", "--event", "e1")
        self.g(self.b, "ask", "--agent", "x", "--question", "Shared question?", "--event", "e2")
        self.g(self.a, "sync", "push", "--message", "a")
        self.g(self.b, "sync", "push", "--message", "b")
        data, _, _ = self.remote_data()
        same = [q for q in data["questions"] if q["question"] == "Shared question?"]
        self.assertEqual(len(same), 1)
        self.assertEqual(same[0]["times_asked"], 2)
        self.assertEqual(sorted(same[0]["events"]), ["e1", "e2"])

    def test_answer_and_tick_concurrently(self):
        self.g(self.a, "answer", "Q1", "--answer", "red", "--rule", "Notes are red.")
        self.g(self.a, "sync", "push", "--message", "answer Q1")
        self.g(self.b, "tick")
        self.g(self.b, "ask", "--agent", "z", "--question", "Another?")
        self.g(self.b, "sync", "push", "--message", "run 2026-10-05 daily")
        data, _, _ = self.remote_data()
        q1 = next(q for q in data["questions"] if q["id"] == "Q1")
        self.assertEqual(q1["status"], "answered")
        self.assertEqual(len(data["rules"]), 1)

    def test_state_and_config_never_pushed(self):
        os.makedirs(os.path.join(self.a, "state", "guarded"), exist_ok=True)
        with open(os.path.join(self.a, "state", "created_events.json"), "w") as fh:
            fh.write("{}")
        with open(os.path.join(self.a, "config.json"), "w") as fh:
            fh.write("{}")
        self.g(self.a, "ask", "--agent", "x", "--question", "Q?")
        self.g(self.a, "sync", "push", "--message", "run")
        _, files, _ = self.remote_data()
        self.assertFalse([f for f in files if f.startswith("state/") or f == "config.json"])

    def test_simultaneous_pushes(self):
        self.g(self.a, "ask", "--agent", "x", "--question", "From A?")
        self.g(self.b, "ask", "--agent", "y", "--question", "From B?")
        errors = []

        def go(home, msg):
            try:
                self.g(home, "sync", "push", "--message", msg)
            except AssertionError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=go, args=(self.a, "run a")),
                   threading.Thread(target=go, args=(self.b, "run b"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors)
        data, _, _ = self.remote_data()
        texts = [q["question"] for q in data["questions"]]
        self.assertIn("From A?", texts)
        self.assertIn("From B?", texts)


if __name__ == "__main__":
    unittest.main()
