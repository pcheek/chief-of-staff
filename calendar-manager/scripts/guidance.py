#!/usr/bin/env python3
"""calendar-manager memory: open questions for Paul and the rules his answers become.

Every run reads guidance.md before acting, so an answer given once is applied from
then on. Data lives in the memory folder (see cm_paths.py): in the cloud, a clone of the
private memory repo that every run pulls from and pushes to; on the desktop,
~/.claude/calendar-manager.

    guidance.json   source of truth: rules + questions
    guidance.md     rendered active rules, read by every agent
    questions.md    rendered open questions
    runs/           one report per run
    state/          guard bookkeeping (gitignored, never committed)
    config          guard config, outside the repo; agents never touch it

    guidance.py where                        print the memory folder, state and config paths
    guidance.py sync pull                    git pull --rebase the memory repo
    guidance.py sync push --message M        commit guidance + runs and push; on a rejected
                                             push, rebase and retry (never force)
    guidance.py init                         create the folder and seed questions
    guidance.py ask --agent A --question Q [--default D] [--context C] [--event ID]
    guidance.py open [--json]                open questions
    guidance.py answer QID --answer TEXT [--rule TEXT] [--scope S]
    guidance.py add-rule --rule TEXT [--scope S] [--source TEXT]
    guidance.py supersede GID --rule TEXT [--source TEXT]
                                             replace a rule with a corrected one
    guidance.py rules [--json]               active rules
    guidance.py tick                         end of run: count a run against every active rule
    guidance.py candidates [--min-runs 2]    rules ready to promote into the plugin SOP
    guidance.py promoted GID [GID ...]       mark rules promoted after the PR merges

Stdlib only.
"""
import argparse
import contextlib
import copy
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:  # pragma: no cover (Windows)
    fcntl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_paths  # noqa: E402

SCRIPT = os.path.realpath(os.path.abspath(__file__))
_P = cm_paths.paths()
HOME, STATE, CONFIG = _P["home"], _P["state"], _P["config"]
DATA = os.path.join(HOME, "guidance.json")
SYNCED = ["guidance.json", "guidance.md", "questions.md", "runs"]
NETWORK_ERRORS = re.compile(r"could not resolve|connection|timed out|unable to access|"
                            r"\b(429|500|502|503|504)\b|early eof|remote end hung up", re.I)
REJECTED = re.compile(r"rejected|non-fast-forward|fetch first|failed to push", re.I)

DEFAULT_CONFIG = {
    "owner_emails": ["paul@cheek.org", "pcheek@mit.edu"],
    "owner_calendars": ["primary"],
    "callie_email": "calliemcheek@gmail.com",
    "travel_color_ids": ["1"],
    "home_timezone": "America/New_York",
}

# Old seed wording -> index of its current wording in SEED_QUESTIONS, so rewording a seed
# never re-asks it.
SEED_ALIASES = {
    "which email is the calendar these runs manage paul cheek org or pcheek mit edu if it "
    "differs from config json owner emails edit claude calendar manager config json yourself "
    "the agents are not allowed to": 3,
}
V01_IDENTITY = next(iter(SEED_ALIASES))

# Seeds Paul has settled outside a run. They're marked seeded and never asked.
RETIRED_SEEDS = [
    "Notes and holds: the 2024 calendar doc says purple, the Apr 2025 SOP says red "
    "(Tomato). Which color marks a note that needs your review?",  # Legend: Needs Review = 11
]

# Gaps and contradictions in the source SOPs. Each run asks until Paul answers.
SEED_QUESTIONS = [
    ("travel-planner",
     "Airport transit: the SOP's flight steps say purple, its color legend says lavender for "
     "travel. Which color for driving to the airport?",
     "Lavender (colorId 1), the travel color. Gray for downtime at the airport."),
    ("one-on-one-auditor",
     "The 1:1 roster in the calendar doc is the MIT Trust Center team from 2024. Which of "
     "those 1:1s still exist, and who is on your current roster with what cadence?",
     "Audit no 1:1s until you confirm a roster."),
    ("commute-planner",
     "Which days and where do you commute now (the doc assumes MIT, 45 minutes, blocked as "
     "one hour)? Is Friday still the standard work-from-home day?",
     "Add drive-time only around in-person events at MIT or in Cambridge/Boston; treat "
     "Friday as WFH."),
    ("categorizer",
     "Which email is the calendar these runs manage (paul@cheek.org or pcheek@mit.edu)? "
     "If it differs from owner_emails in your config (the CALENDAR_MANAGER_CONFIG_JSON "
     "environment variable in the cloud, config.json on the desktop), change it yourself: "
     "the agents are not allowed to.",
     "Both addresses count as you."),
    ("travel-planner",
     "When you travel, do you switch Google Calendar's display time zone to where you are, "
     "or keep it on Boston? (Events are written with exact offsets either way; this only "
     "changes how the run report and new events are labeled.)",
     "Keep the calendar on Boston; reports show local time with Boston in parentheses."),
    ("offered-times-tracker",
     "Who schedules on your behalf (EA, team members), so the times they offer by email "
     "count as yours and get held on your calendar?",
     "Anyone who writes that you are available or could do a time."),
]


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def load():
    try:
        with open(DATA, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("rules", [])
    data.setdefault("questions", [])
    return data


@contextlib.contextmanager
def locked():
    """One writer at a time in this container: parallel agents asking questions, and a
    sync, never interleave a load/save."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, ".lock"), "w") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


def save(data):
    os.makedirs(HOME, exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, DATA)
    render(data)


def next_id(items, prefix):
    nums = [int(i["id"][len(prefix):]) for i in items if i["id"].startswith(prefix)
            and i["id"][len(prefix):].isdigit()]
    return "%s%d" % (prefix, max(nums, default=0) + 1)


def render(data):
    rules = [r for r in data["rules"] if r["status"] == "active"]
    lines = [
        "# Calendar guidance from Paul",
        "",
        "Generated by guidance.py; do not edit by hand. Rules here override the plugin SOP",
        "(skills/calendar-sop) where they conflict. They never override the guard: no rule",
        "can allow deleting events, inviting anyone but Callie to travel, or messaging people.",
        "",
    ]
    if not rules:
        lines.append("_No rules yet._")
    by_scope = {}
    for r in rules:
        by_scope.setdefault(r["scope"], []).append(r)
    for scope in sorted(by_scope):
        lines += ["", "## %s" % scope, ""]
        for r in by_scope[scope]:
            lines.append("- **%s** (%s): %s" % (r["id"], r["created"][:10], r["rule"]))
    with open(os.path.join(HOME, "guidance.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    open_qs = [q for q in data["questions"] if q["status"] == "open"]
    q_lines = ["# Open questions for Paul", ""]
    if not open_qs:
        q_lines.append("_None._")
    for q in open_qs:
        q_lines.append("- **%s** [%s, asked %s x%d] %s" % (
            q["id"], q["agent"], q["created"][:10], q["times_asked"], q["question"]))
        if q.get("default"):
            q_lines.append("  - Default until answered: %s" % q["default"])
        if q.get("context"):
            q_lines.append("  - Context: %s" % q["context"])
    with open(os.path.join(HOME, "questions.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(q_lines) + "\n")


def add_question(data, agent, question, default="", context="", event=""):
    key = norm(question)
    for q in data["questions"]:
        if q["status"] == "open" and norm(q["question"]) == key:
            q["times_asked"] += 1
            q["last_asked"] = now()
            if event and event not in q["events"]:
                q["events"].append(event)
            return q, False
    q = {
        "id": next_id(data["questions"], "Q"), "agent": agent, "question": question,
        "default": default, "context": context, "events": [event] if event else [],
        "status": "open", "created": now(), "last_asked": now(), "times_asked": 1,
    }
    data["questions"].append(q)
    return q, True


def add_rule(data, rule, scope, source):
    r = {
        "id": next_id(data["rules"], "G"), "rule": rule, "scope": scope or "all",
        "source": source, "status": "active", "created": now(), "runs_seen": 0,
    }
    data["rules"].append(r)
    return r


def find(items, item_id):
    for it in items:
        if it["id"].lower() == item_id.lower():
            return it
    sys.exit("no such id: %s" % item_id)


def is_repo():
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HOME, text=True,
                             capture_output=True)
    except OSError:
        return False
    return top.returncode == 0 and os.path.realpath(top.stdout.strip()) == HOME


def ignored(rel):
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=HOME).returncode == 0


def check_config():
    if os.environ.get("CALENDAR_MANAGER_CONFIG_JSON"):
        print("config: CALENDAR_MANAGER_CONFIG_JSON (environment)")
    elif os.path.exists(CONFIG):
        print("config: %s" % CONFIG)
    elif os.environ.get("CALENDAR_MANAGER_CONFIG"):
        print("WARNING: %s is missing. The environment's setup script should write it; the "
              "guard is using its built-in defaults." % CONFIG)
    elif is_repo() and not ignored("config.json"):
        print("WARNING: no config, and config.json is not gitignored here, so none was "
              "written. The guard is using its built-in defaults.")
    else:
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CONFIG, fh, indent=2)
        print("wrote %s" % CONFIG)
    if is_repo():
        for rel in ("state/x", "config.json"):
            if not ignored(rel):
                print("WARNING: %s is not gitignored in %s. Add state/ and config.json to "
                      ".gitignore." % (rel.split("/")[0], HOME))


def cmd_where(args, data):
    # The guard keeps the config file itself off limits, so print the routing agents need:
    # which calendar to write to and through whose connector. None of it is secret.
    cfg = cm_paths.load_config(CONFIG, {})
    routing = {k: cfg.get(k) for k in ("calendar_id", "agent_identity", "writer_servers",
                                       "home_timezone") if cfg.get(k)}
    print(json.dumps({"home": HOME, "state": STATE, "config": CONFIG,
                      "config_from_env": bool(os.environ.get("CALENDAR_MANAGER_CONFIG_JSON")),
                      "routing": routing,
                      "guidance": os.path.join(HOME, "guidance.md"),
                      "questions": os.path.join(HOME, "questions.md"),
                      "runs": os.path.join(HOME, "runs"), "git_repo": is_repo()}, indent=1))


def cmd_init(args, data):
    os.makedirs(os.path.join(HOME, "runs"), exist_ok=True)
    keep = os.path.join(HOME, "runs", ".gitkeep")
    if not os.path.exists(keep):
        open(keep, "w").close()
    check_config()
    # Seed per question, so a seed added in a later version still reaches old installs,
    # and one Paul already answered is never asked again.
    seeded = data.setdefault("seeded_keys", [])
    if data.get("seeded") and not seeded:  # v0.1 seeded all of its questions at once
        # v0.1 asked: notes color (now retired), airport, roster, commute, old identity wording
        seeded.extend([norm(q) for _, q, _ in SEED_QUESTIONS[:3]] + [V01_IDENTITY])
    for old, idx in SEED_ALIASES.items():
        new = norm(SEED_QUESTIONS[idx][1])
        if old in seeded and new not in seeded:
            seeded.append(new)
    for retired in RETIRED_SEEDS:
        if norm(retired) not in seeded:
            seeded.append(norm(retired))
    for agent, question, default in SEED_QUESTIONS:
        key = norm(question)
        if key not in seeded:
            add_question(data, agent, question, default)
            seeded.append(key)
    data["seeded"] = data.get("seeded") or now()
    save(data)
    print("ready: %s" % HOME)


def cmd_ask(args, data):
    q, new = add_question(data, args.agent, args.question, args.default or "",
                          args.context or "", args.event or "")
    save(data)
    print("%s %s" % (q["id"], "new" if new else "already open (asked %dx)" % q["times_asked"]))


def cmd_open(args, data):
    qs = [q for q in data["questions"] if q["status"] == "open"]
    if args.json:
        print(json.dumps(qs, indent=1))
        return
    for q in qs:
        print("%s [%s] %s\n    default: %s" % (q["id"], q["agent"], q["question"],
                                               q.get("default") or "-"))


def cmd_answer(args, data):
    q = find(data["questions"], args.qid)
    q.update(status="answered", answer=args.answer, answered=now())
    rule = add_rule(data, args.rule or args.answer, args.scope or q["agent"],
                    "Paul, answering %s: %s" % (q["id"], q["question"]))
    q["rule"] = rule["id"]
    save(data)
    print("%s answered -> rule %s" % (q["id"], rule["id"]))


def cmd_add_rule(args, data):
    r = add_rule(data, args.rule, args.scope, args.source or "Paul")
    save(data)
    print(r["id"])


def cmd_supersede(args, data):
    old = find(data["rules"], args.gid)
    source = "%s, correcting %s" % (args.source or "Paul", old["id"])
    new = add_rule(data, args.rule, args.scope or old["scope"], source)
    old.update(status="superseded", superseded_by=new["id"])
    save(data)
    print("%s superseded by %s" % (old["id"], new["id"]))


def cmd_rules(args, data):
    rules = [r for r in data["rules"] if r["status"] == "active"]
    if args.json:
        print(json.dumps(rules, indent=1))
        return
    for r in rules:
        print("%s [%s] %s" % (r["id"], r["scope"], r["rule"]))


def cmd_tick(args, data):
    for r in data["rules"]:
        if r["status"] == "active":
            r["runs_seen"] += 1
    save(data)
    print("ticked %d rules" % sum(r["status"] == "active" for r in data["rules"]))


def cmd_candidates(args, data):
    out = [r for r in data["rules"] if r["status"] == "active" and not r.get("promoted")
           and r["runs_seen"] >= args.min_runs]
    print(json.dumps(out, indent=1))


def cmd_promoted(args, data):
    for gid in args.gids:
        find(data["rules"], gid)["promoted"] = now()
    save(data)
    print("marked %d promoted" % len(args.gids))


# ---------------------------------------------------------------- merging concurrent runs

def _identity(coll, item):
    if coll == "questions":
        return norm(item.get("question", ""))
    return (item.get("rule"), item.get("created"))


def _combine(coll, a, b, base):
    """Fold b (our replayed change) into a (upstream) for the same item."""
    if coll == "questions":
        if b.get("status") == "answered" and a.get("status") != "answered":
            for k in ("status", "answer", "answered", "rule"):
                if k in b:
                    a[k] = b[k]
        grown = b.get("times_asked", 0) - (base or {}).get("times_asked", 0)
        a["times_asked"] = a.get("times_asked", 0) + max(0, grown)
        a["last_asked"] = max(a.get("last_asked", ""), b.get("last_asked", ""))
        a["events"] = list(dict.fromkeys((a.get("events") or []) + (b.get("events") or [])))
    else:
        if b.get("status") == "superseded" and a.get("status") != "superseded":
            a["status"], a["superseded_by"] = "superseded", b.get("superseded_by")
        a["runs_seen"] = a.get("runs_seen", 0) + max(
            0, b.get("runs_seen", 0) - (base or {}).get("runs_seen", 0))
        if b.get("promoted") and not a.get("promoted"):
            a["promoted"] = b["promoted"]


def merge_data(o, a, b):
    """Three-way merge of guidance.json. a is the upstream side, b the change being
    replayed. Items are never deleted, so the merge is a union: changes to the same item
    are folded together, and a new item whose id the other side already used is
    renumbered."""
    out = copy.deepcopy(a)
    out.setdefault("rules", [])
    out.setdefault("questions", [])
    remap = {"questions": {}, "rules": {}}
    for coll, prefix in (("rules", "G"), ("questions", "Q")):
        base_by = {x["id"]: x for x in o.get(coll, [])}
        out_by = {x["id"]: x for x in out[coll]}
        for item in b.get(coll, []):
            base = base_by.get(item["id"])
            if base == item:
                continue
            cur = out_by.get(item["id"])
            if cur is not None and _identity(coll, cur) == _identity(coll, item):
                _combine(coll, cur, item, base)
                continue
            if coll == "questions":
                dup = next((q for q in out[coll] if q.get("status") == "open"
                            and _identity(coll, q) == _identity(coll, item)), None)
                if dup is not None:
                    _combine(coll, dup, item, None)
                    remap[coll][item["id"]] = dup["id"]
                    continue
            item = copy.deepcopy(item)
            if item["id"] in out_by:
                new_id = next_id(out[coll], prefix)
                remap[coll][item["id"]] = new_id
                item["id"] = new_id
            out[coll].append(item)
            out_by[item["id"]] = item
    for q in out["questions"]:
        if q.get("rule") in remap["rules"]:
            q["rule"] = remap["rules"][q["rule"]]
    for r in out["rules"]:
        if r.get("superseded_by") in remap["rules"]:
            r["superseded_by"] = remap["rules"][r["superseded_by"]]
        for old, new in remap["questions"].items():
            r["source"] = re.sub(r"\b%s\b" % re.escape(old), new, r.get("source", ""))
    keys = list(dict.fromkeys(a.get("seeded_keys", []) + b.get("seeded_keys", [])))
    if keys:
        out["seeded_keys"] = keys
    seeded = [s for s in (a.get("seeded"), b.get("seeded")) if s]
    if seeded:
        out["seeded"] = min(seeded)
    return out


def cmd_merge_driver(args, data):
    """git merge driver for guidance.json: python3 guidance.py merge-driver %O %A %B"""
    try:
        parts = []
        for path in (args.base, args.ours, args.theirs):
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
            parts.append(json.loads(text) if text else {})
    except (OSError, ValueError):
        sys.exit(1)  # leave it as a conflict; sync aborts the rebase
    merged = merge_data(*parts)
    with open(args.ours, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=1)


# ---------------------------------------------------------------- git sync

def git(*args, check=False):
    return subprocess.run(["git", *args], cwd=HOME, text=True, capture_output=True)


def with_network_retry(fn):
    """Retry fn on network errors: 2s, 4s, 8s, 16s."""
    for delay in (2, 4, 8, 16, None):
        res = fn()
        if res.returncode == 0 or not NETWORK_ERRORS.search(res.stderr or ""):
            return res
        if delay is None:
            return res
        print("network error, retrying in %ds: %s" % (delay, res.stderr.strip()[:200]))
        time.sleep(delay)


def branch():
    """The memory repo's shared branch: $CALENDAR_MANAGER_MEMORY_BRANCH, else main.
    Never the checked-out branch: a cloud session starts on its own claude/<name> branch,
    and memory pushed there is invisible to every later run."""
    return os.environ.get("CALENDAR_MANAGER_MEMORY_BRANCH") or "main"


ATTRIBUTES = ("guidance.json merge=calendar-guidance\n"
              "guidance.md merge=calendar-render\n"
              "questions.md merge=calendar-render\n")


def configure_git():
    """Merge drivers live in this clone's git config, and their file mapping in
    .git/info/attributes, so a fresh cloud clone merges correctly even if the repo's
    own .gitattributes is missing or edited."""
    gitdir = git("rev-parse", "--git-dir").stdout.strip()
    info = os.path.join(HOME, gitdir, "info")
    os.makedirs(info, exist_ok=True)
    attrs = os.path.join(info, "attributes")
    try:
        with open(attrs, encoding="utf-8") as fh:
            current = fh.read()
    except OSError:
        current = ""
    if ATTRIBUTES not in current:
        with open(attrs, "a", encoding="utf-8") as fh:
            fh.write(("\n" if current and not current.endswith("\n") else "") + ATTRIBUTES)
    driver = "python3 '%s' merge-driver %%O %%A %%B" % SCRIPT
    git("config", "merge.calendar-guidance.name", "calendar-manager guidance.json union merge")
    git("config", "merge.calendar-guidance.driver", driver)
    git("config", "merge.calendar-render.name", "keep upstream; guidance.py re-renders")
    git("config", "merge.calendar-render.driver", "true")
    if not git("config", "user.email").stdout.strip():
        git("config", "user.email", "calendar-manager@users.noreply.github.com")
    if not git("config", "user.name").stdout.strip():
        git("config", "user.name", "calendar-manager")


def remote_has_branch(br):
    res = with_network_retry(lambda: git("ls-remote", "--heads", "origin", br))
    return res.returncode == 0 and bool(res.stdout.strip())


def rebase_in_progress():
    gitdir = git("rev-parse", "--git-dir").stdout.strip()
    return any(os.path.exists(os.path.join(HOME, gitdir, d))
               for d in ("rebase-merge", "rebase-apply"))


def pull():
    if not is_repo():
        print("not a git repo (%s): nothing to pull" % HOME)
        return True
    configure_git()
    br = branch()
    if not remote_has_branch(br):
        print("origin/%s does not exist yet: nothing to pull" % br)
        return True
    res = with_network_retry(lambda: git("pull", "--rebase", "--autostash", "origin", br))
    if res.returncode != 0:
        if rebase_in_progress():
            git("rebase", "--abort")
        print("pull failed, left local commits as they were:\n%s" % res.stderr.strip())
        return False
    print("pulled origin/%s" % br)
    return True


def commit_synced(message):
    paths = [p for p in SYNCED if os.path.exists(os.path.join(HOME, p))]
    if paths:
        git("add", "--", *paths)
    if git("diff", "--cached", "--quiet").returncode != 0:
        res = git("commit", "-m", message)
        if res.returncode != 0:
            sys.exit("commit failed: %s" % res.stderr.strip())
        return True
    return False


def push(message, attempts=6):
    if not is_repo():
        print("not a git repo (%s): nothing to push" % HOME)
        return True
    configure_git()
    br = branch()
    render(load())
    commit_synced(message)
    if git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        print("nothing committed yet: nothing to push")
        return True
    for attempt in range(1, attempts + 1):
        res = with_network_retry(lambda: git("push", "origin", "HEAD:%s" % br))
        if res.returncode == 0:
            print("pushed to origin/%s" % br)
            return True
        if not REJECTED.search(res.stderr or ""):
            print("push failed:\n%s" % res.stderr.strip())
            return False
        # Another run pushed first. Rebase onto it (the merge driver folds guidance.json
        # together), re-render, and try again. Never force.
        print("push rejected (attempt %d), rebasing onto origin/%s" % (attempt, br))
        if not pull():
            return False
        render(load())
        commit_synced("%s (re-rendered after rebase)" % message)
        time.sleep(min(2 * attempt, 10))
    print("push still rejected after %d attempts; the commit is kept locally and the next "
          "sync pushes it" % attempts)
    return False


def cmd_sync(args, data):
    ok = pull() if args.action == "pull" else push(args.message or "sync")
    sys.exit(0 if ok else 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("where")
    p = sub.add_parser("sync")
    p.add_argument("action", choices=["pull", "push"])
    p.add_argument("--message", "-m")
    p = sub.add_parser("merge-driver")
    p.add_argument("base")
    p.add_argument("ours")
    p.add_argument("theirs")
    p = sub.add_parser("ask")
    p.add_argument("--agent", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--default")
    p.add_argument("--context")
    p.add_argument("--event")
    p = sub.add_parser("open")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("answer")
    p.add_argument("qid")
    p.add_argument("--answer", required=True)
    p.add_argument("--rule")
    p.add_argument("--scope")
    p = sub.add_parser("add-rule")
    p.add_argument("--rule", required=True)
    p.add_argument("--scope", default="all")
    p.add_argument("--source")
    p = sub.add_parser("supersede")
    p.add_argument("gid")
    p.add_argument("--rule", required=True)
    p.add_argument("--scope")
    p.add_argument("--source")
    p = sub.add_parser("rules")
    p.add_argument("--json", action="store_true")
    sub.add_parser("tick")
    p = sub.add_parser("candidates")
    p.add_argument("--min-runs", type=int, default=2)
    p = sub.add_parser("promoted")
    p.add_argument("gids", nargs="+")
    args = ap.parse_args()
    if args.cmd == "merge-driver":  # runs inside a locked sync; must not lock again
        return cmd_merge_driver(args, None)
    with locked():
        data = load()
        {
            "init": cmd_init, "ask": cmd_ask, "open": cmd_open, "answer": cmd_answer,
            "add-rule": cmd_add_rule, "supersede": cmd_supersede, "rules": cmd_rules,
            "tick": cmd_tick, "candidates": cmd_candidates, "promoted": cmd_promoted,
            "where": cmd_where, "sync": cmd_sync,
        }[args.cmd](args, data)


if __name__ == "__main__":
    main()
