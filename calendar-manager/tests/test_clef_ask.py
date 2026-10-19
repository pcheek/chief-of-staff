"""Offline tests for scripts/clef_ask.py. Run: python3 -m unittest discover -s calendar-manager/tests"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import clef_ask as ca  # noqa: E402


def noul(p):
    return {"type": "noul", "noul": p}


def choice(c, top, other="other"):
    return {"type": "choice", "choice": c, "confidence": 0.3, "probabilities": {c: top, other: round(1 - top, 4)}}


def ctx(**kw):
    return {"url": "https://x/{model}", "token": "t", "model": "clef-flash", "escalate_model": "clef"} | kw


Q = {"q": {"type": "noul", "instructions": "?"}, "c": {"type": "choice", "instructions": "?", "criteria": {"a": "A", "b": "B"}}}


class VerdictTests(unittest.TestCase):
    def test_noul_verdicts(self):
        self.assertEqual(ca.simplify(noul(0.9))["verdict"], "yes")
        self.assertEqual(ca.simplify(noul(0.1))["verdict"], "no")
        self.assertEqual(ca.simplify(noul(0.5))["verdict"], "unsure")

    def test_choice_uses_the_top_probability_not_clefs_confidence(self):
        # Clef's own `confidence` runs far below the top probability (0.39 vs 0.547 on a live
        # receipt), so the verdict reads the probability.
        a = ca.simplify(choice("receipt", 0.65))
        self.assertEqual((a["verdict"], a["top_p"]), ("receipt", 0.65))
        self.assertEqual(ca.simplify(choice("receipt", 0.547))["verdict"], "unsure")

    def test_choice_below_the_bar_is_unsure(self):
        self.assertEqual(ca.simplify(choice("a", 0.45))["verdict"], "unsure")

    def test_per_question_bar_overrides(self):
        self.assertEqual(ca.simplify(noul(0.9), {"yes_min": 0.95})["verdict"], "unsure")
        self.assertEqual(ca.simplify(noul(0.04), {"no_max": 0.05})["verdict"], "no")

    def test_score_has_no_verdict(self):
        self.assertNotIn("verdict", ca.simplify({"type": "score", "score": 2.0, "confidence": 0.5}))


class AskTests(unittest.TestCase):
    def test_clear_answers_are_not_escalated(self):
        raw = {"model": "clef-flash", "answers": {"q": noul(0.97), "c": choice("a", 0.9)}, "usage": {"input_tokens": 100}}
        with mock.patch.object(ca, "post", return_value=raw) as m:
            r = ca.ask_one({"id": "x", "state": "s", "questions": Q}, ctx())
        self.assertEqual(m.call_count, 1)
        self.assertEqual((r["ok"], r["escalated"], r["answers"]["q"]["verdict"]), (True, False, "yes"))

    def test_only_gray_questions_are_asked_again_with_the_larger_model(self):
        first = {"model": "clef-flash", "answers": {"q": noul(0.5), "c": choice("a", 0.9)}, "usage": {"input_tokens": 100}}
        second = {"model": "clef", "answers": {"q": noul(0.97)}, "usage": {"input_tokens": 110}}
        with mock.patch.object(ca, "post", side_effect=[first, second]) as m:
            r = ca.ask_one({"id": "x", "state": "s", "questions": Q}, ctx())
        self.assertEqual(list(m.call_args_list[1][0][2]["questions"]), ["q"])
        self.assertEqual((r["answers"]["q"]["verdict"], r["escalated"], r["input_tokens"]), ("yes", True, 210))

    def test_still_unsure_stays_unsure(self):
        raw = {"model": "clef", "answers": {"q": noul(0.5), "c": choice("a", 0.9)}, "usage": {"input_tokens": 1}}
        with mock.patch.object(ca, "post", return_value=raw):
            r = ca.ask_one({"id": "x", "state": "s", "questions": Q}, ctx())
        self.assertEqual(r["answers"]["q"]["verdict"], "unsure")

    def test_escalation_failure_keeps_the_first_answer(self):
        first = {"model": "clef-flash", "answers": {"q": noul(0.5), "c": choice("a", 0.9)}, "usage": {}}
        with mock.patch.object(ca, "post", side_effect=[first, ca.ClefError("HTTP 500")]):
            r = ca.ask_one({"id": "x", "state": "s", "questions": Q}, ctx())
        self.assertTrue(r["ok"])
        self.assertIn("escalation_error", r)

    def test_bad_question_type_fails_loud(self):
        r = ca.ask_one({"id": "x", "state": "s", "questions": {"q": {"type": "essay", "instructions": "?"}}}, ctx())
        self.assertFalse(r["ok"])

    def test_error_never_becomes_an_answer(self):
        with mock.patch.object(ca, "post", side_effect=ca.ClefError("HTTP 401")):
            r = ca.ask_one({"id": "x", "state": "s", "questions": Q}, ctx())
        self.assertEqual((r["ok"], "answers" in r), (False, False))


class CommandTests(unittest.TestCase):
    def run_cmd(self, argv_extra, payload, side_effect, env=None):
        with tempfile.TemporaryDirectory() as d:
            inp, out = os.path.join(d, "in.json"), os.path.join(d, "out.json")
            ca.dump(payload, inp)
            env = {"CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_AUTH_TOKEN": "SECRET-TOKEN-123"} if env is None else env
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(ca, "post", side_effect=side_effect):
                code = ca.main(["--in", inp, "--out", out, "--workers", "1", *argv_extra])
            return code, (ca.load(out) if os.path.exists(out) else None)

    def test_round_trip_and_token_never_in_output(self):
        raw = {"model": "clef-flash", "answers": {"q": noul(0.97)}, "usage": {"input_tokens": 100}}
        payload = {"items": [{"id": "k1", "state": "s", "questions": {"q": Q["q"]}}]}
        code, out = self.run_cmd([], payload, [raw])
        self.assertEqual(code, 0)
        self.assertEqual(out["results"]["k1"]["answers"]["q"]["verdict"], "yes")
        self.assertNotIn("SECRET-TOKEN-123", json.dumps(out))

    def test_missing_account_id_exit_3(self):
        code, out = self.run_cmd([], {"items": []}, [], env={})
        self.assertEqual((code, out), (3, None))

    def test_every_failure_exit_4(self):
        payload = {"items": [{"id": "k1", "state": "s", "questions": {"q": Q["q"]}}]}
        code, _ = self.run_cmd([], payload, [ca.ClefError("HTTP 401")])
        self.assertEqual(code, 4)

    def test_inline_json_prints_answers_to_stdout(self):
        import contextlib
        import io
        raw = {"model": "clef-flash", "answers": {"q": noul(0.97)}, "usage": {"input_tokens": 100}}
        payload = json.dumps({"items": [{"id": "k1", "state": "Paul\u0027s note", "questions": {"q": Q["q"]}}]})
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": "acct"}, clear=True), \
                mock.patch.object(ca, "post", return_value=raw), contextlib.redirect_stdout(buf):
            code = ca.main(["--json", payload])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["results"]["k1"]["answers"]["q"]["verdict"], "yes")

    def test_bad_inline_json_exit_2(self):
        with mock.patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": "acct"}, clear=True):
            self.assertEqual(ca.main(["--json", "{not json"]), 2)

    def test_probe(self):
        with mock.patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": "acct"}, clear=True):
            with mock.patch.object(ca, "post", return_value={"model": "clef-flash", "answers": {"q": noul(0.9)}, "usage": {}}):
                self.assertEqual(ca.main(["--probe"]), 0)
            with mock.patch.object(ca, "post", side_effect=ca.ClefError("HTTP 403")):
                self.assertEqual(ca.main(["--probe"]), 4)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ca.main(["--probe"]), 3)


class RetryAndAuthTests(unittest.TestCase):
    def headers(self, token):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(ca.urllib.request, "urlopen", return_value=ok) as m:
            ca.post("https://x", token, {})
        return {k.lower(): v for k, v in m.call_args[0][0].header_items()}

    def test_bearer_only_when_a_token_is_set(self):
        self.assertEqual(self.headers("abc")["authorization"], "Bearer abc")
        self.assertNotIn("authorization", self.headers(None))

    def test_retries_429_but_not_400(self):
        err = ca.urllib.error.HTTPError("u", 429, "slow", {"Retry-After": "0"}, None)
        err.read = lambda: b"{}"
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"answers": {}}'
        with mock.patch.object(ca.urllib.request, "urlopen", side_effect=[err, ok]), mock.patch.object(ca.time, "sleep"):
            self.assertEqual(ca.post("https://x", "t", {}), {"answers": {}})
        bad = ca.urllib.error.HTTPError("u", 400, "bad", {}, None)
        bad.read = lambda: b"bad"
        with mock.patch.object(ca.urllib.request, "urlopen", side_effect=[bad]) as m:
            with self.assertRaises(ca.ClefError):
                ca.post("https://x", "t", {})
            self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
