#!/usr/bin/env python3
"""Every classification in calendar-manager goes through here. No Claude model classifies.

Clef (Cloudflare's decision model, Jev-API compatible) answers typed questions with
probabilities instead of text. An agent retrieves and writes; whenever it needs a yes/no, a
category, or a ranking, it writes an ask file and runs this script. Stdlib only.

    python3 clef_ask.py --json '<ask json>' [--model clef-flash] [--escalate-model clef]
    python3 clef_ask.py --in ask.json --out answers.json      # the same, through files
    python3 clef_ask.py --probe          # one trivial question: is Clef reachable?

`--json` prints the answers to stdout, so agents need no scratch files (they have no Write
tool). Write every apostrophe inside the JSON as \u0027 so the single-quoted shell argument
never breaks.

ask.json:
    {"items": [{"id": "ev1",
                "state": {...anything: the event, the email, the note, the facts...},
                "questions": {"q": {"type": "noul", "instructions": "..."},
                              "c": {"type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."}},
                              "s": {"type": "score", "instructions": "...", "criteria": ["low", "...", "high"]}},
                "accept": {"q": {"yes_min": 0.95, "no_max": 0.05}}}]}     # optional, per question

answers.json: per item id, `answers.<q>`:
    noul    {"p": 0.91, "verdict": "yes" | "no" | "unsure"}
    choice  {"choice": "a", "top_p": 0.82, "probabilities": {...}, "verdict": "a" | "unsure"}
    score   {"score": 2.4, "confidence": 0.5}
A verdict is `yes` at p >= 0.85, `no` at p <= 0.15, and `unsure` between. A choice verdict is
the top choice when its probability is >= 0.60, otherwise `unsure`. **Act only on a decisive
verdict. On `unsure`, never decide it yourself: ask Paul (`guidance.py ask`) and leave the
event alone.** A result in the gray band is asked again once with the larger model.

Credentials, never in a file, a prompt, or a report:
    CLOUDFLARE_ACCOUNT_ID   required, an environment variable on the calendar-manager environment.
    The API token           a Bearer network secret on api.cloudflare.com (the agent proxy adds
                            it outside the VM). Fallback: CLOUDFLARE_AUTH_TOKEN.
    The token needs Workers AI - Read and Workers AI - Edit on one account.

Exit codes: 0 done (per-item errors listed), 2 bad input, 3 account id missing, 4 every item
failed (a 401 or 403 usually means the network secret is missing).

Same client as cheek-chief-of-staff's scripts/clef_classify.py (its `ask` command), kept
separate because each plugin is vendored on its own.
API: https://developers.cloudflare.com/workers-ai/models/clef-flash/
"""
import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
MODELS = ("clef", "clef-flash")
QUESTION_TYPES = ("noul", "choice", "score")
DEFAULTS = {"yes_min": 0.85, "no_max": 0.15, "choice_min": 0.60,
            "gray_low": 0.10, "gray_high": 0.90, "gray_choice": 0.70}


class ClefError(Exception):
    pass


def load(path):
    with open(path) as fh:
        return json.load(fh)


def dump(obj, path):
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1)


def post(url, token, payload, timeout=30, attempts=3):
    """POST JSON with retry on 429 and 5xx. Returns the parsed response body."""
    data = json.dumps(payload).encode()
    last = None
    for attempt in range(attempts):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            last = "HTTP %s: %s" % (e.code, body)
            if e.code in (401, 403) and not token:
                last += " (no CLOUDFLARE_AUTH_TOKEN set: is the api.cloudflare.com network secret on this environment?)"
            if e.code not in (429, 500, 502, 503, 504):
                raise ClefError(last)
            wait = float(e.headers.get("Retry-After") or 2 ** attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = "%s: %s" % (type(e).__name__, e)
            wait = 2 ** attempt
        if attempt < attempts - 1:
            time.sleep(min(wait, 20))
    raise ClefError("gave up after %d attempts: %s" % (attempts, last))


def unwrap(response):
    if isinstance(response, dict) and isinstance(response.get("result"), dict) and "answers" in response["result"]:
        return response["result"]
    return response


def evaluate(ctx, model, state, questions):
    payload = {"model": model, "state": state, "questions": questions}
    return unwrap(post(ctx["url"].replace("{model}", model), ctx["token"], payload))


def simplify(answer, accept=None):
    """One Clef answer in the shape agents read, with a verdict."""
    t = dict(DEFAULTS, **(accept or {}))
    kind = answer.get("type")
    if kind == "noul":
        p = float(answer["noul"])
        verdict = "yes" if p >= t["yes_min"] else "no" if p <= t["no_max"] else "unsure"
        return {"type": "noul", "p": p, "verdict": verdict}
    if kind == "choice":
        probs = {k: float(v) for k, v in answer["probabilities"].items()}
        top = answer["choice"]
        top_p = probs.get(top, 0.0)
        return {"type": "choice", "choice": top, "top_p": top_p, "probabilities": probs,
                "verdict": top if top_p >= t["choice_min"] else "unsure"}
    if kind == "score":
        return {"type": "score", "score": float(answer["score"]), "confidence": float(answer["confidence"])}
    raise ClefError("unknown answer type: %r" % kind)


def is_gray(a, accept=None):
    t = dict(DEFAULTS, **(accept or {}))
    if a["type"] == "noul":
        return t["gray_low"] <= a["p"] <= t["gray_high"]
    if a["type"] == "choice":
        return a["top_p"] < t["gray_choice"]
    return False


def ask_one(item, ctx):
    out = {"ok": False}
    try:
        questions = item.get("questions") or {}
        accept = item.get("accept") or {}
        if not 1 <= len(questions) <= 64 or any(q.get("type") not in QUESTION_TYPES for q in questions.values()):
            raise ClefError("questions must be 1 to 64 typed questions (noul, choice, score)")
        raw = evaluate(ctx, ctx["model"], item.get("state"), questions)
        answers = {qid: simplify(a, accept.get(qid)) for qid, a in (raw.get("answers") or {}).items()}
        tokens, model, escalated = (raw.get("usage") or {}).get("input_tokens", 0), raw.get("model", ctx["model"]), False
        gray = [q for q, a in answers.items() if is_gray(a, accept.get(q))]
        if gray and ctx["escalate_model"] and ctx["escalate_model"] != ctx["model"]:
            try:
                raw2 = evaluate(ctx, ctx["escalate_model"], item.get("state"), {q: questions[q] for q in gray})
                for qid, a in (raw2.get("answers") or {}).items():
                    answers[qid] = simplify(a, accept.get(qid))
                tokens += (raw2.get("usage") or {}).get("input_tokens", 0)
                escalated = True
                out["escalated_questions"] = gray
            except ClefError as e:
                out["escalation_error"] = str(e)
        missing = [q for q in questions if q not in answers]
        if missing:
            raise ClefError("answers missing for: " + ", ".join(missing))
        out.update(ok=True, model=model, escalated=escalated, answers=answers, input_tokens=tokens)
    except ClefError as e:
        out["error"] = str(e)
    return out


def make_ctx(args):
    account, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_AUTH_TOKEN")
    if not account:
        return None
    esc = None if args.escalate_model in (None, "", "none") else args.escalate_model
    return {"url": API.format(account=account, model="{model}"), "token": token,
            "model": args.model, "escalate_model": esc}


def no_account():
    print(json.dumps({"ok": False, "error": "CLOUDFLARE_ACCOUNT_ID must be set as an environment variable"}))
    return 3


def cmd_probe(args):
    ctx = make_ctx(args)
    if ctx is None:
        return no_account()
    item = {"id": "probe", "state": "The meeting is on Tuesday at 3pm.",
            "questions": {"q": {"type": "noul", "instructions": "Does the text mention a day of the week?"}}}
    out = ask_one(item, dict(ctx, escalate_model=None))
    print(json.dumps({"ok": out["ok"], "error": out.get("error")}))
    return 0 if out["ok"] else 4


def cmd_ask(args):
    try:
        items = (json.loads(args.json) if args.json else load(args.infile))["items"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps({"ok": False, "error": "bad input: %s" % e}))
        return 2
    ctx = make_ctx(args)
    if ctx is None:
        return no_account()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        outs = list(pool.map(lambda it: ask_one(it, ctx), items))
    ok = [o for o in outs if o["ok"]]
    summary = {"items": len(outs), "ok": len(ok), "errors": len(outs) - len(ok),
               "escalated": sum(1 for o in ok if o["escalated"]), "input_tokens": sum(o["input_tokens"] for o in ok)}
    result = {"summary": summary, "results": {it.get("id"): o for it, o in zip(items, outs)}}
    if args.out:
        dump(result, args.out)
        print(json.dumps(summary))
    else:
        print(json.dumps(result))
    return 4 if outs and not ok else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="infile")
    ap.add_argument("--json", help="the ask file's content, inline")
    ap.add_argument("--out", help="write answers here; without it they print to stdout")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--model", default="clef-flash", choices=MODELS)
    ap.add_argument("--escalate-model", default="clef", help="clef, clef-flash, or none")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.probe:
        return cmd_probe(args)
    if not args.infile and not args.json:
        ap.error("--json or --in is required (or use --probe)")
    return cmd_ask(args)


if __name__ == "__main__":
    sys.exit(main())
