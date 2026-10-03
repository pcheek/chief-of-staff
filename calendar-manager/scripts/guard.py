#!/usr/bin/env python3
"""calendar-manager guard: the hook that keeps the calendar agents inside their lane.

Runs on UserPromptSubmit, PreToolUse and PostToolUse. It only enforces inside a
calendar-manager run; every other Claude session passes straight through.

    UserPromptSubmit  a prompt that invokes /calendar-manager:* marks the session guarded
    PreToolUse        in a guarded session: deny deletes, invites, RSVPs, outbound
                      messages, raw Calendar API calls and edits to the guard's own state
    PostToolUse       in a guarded session: remember events the agents created and events
                      a read showed to be solo, so later solo-only edits can be verified

What a guarded session may do to Google Calendar:
  * create events on Paul's own calendar with no guests and no Meet link
  * on any event: change colorId and availability (free/busy), notificationLevel NONE
  * on a solo event it created, or one a read in this session showed to be solo within
    the last 30 minutes: also change time, title, description, location and reminders
  * invite exactly one person, Callie, to a qualifying travel event (see callie_ok)
  * every timed start/end carries an explicit UTC offset, and any timeZone agrees with it
  * nothing in the past is ever created or edited, and an event must be read (get, list or
    search) in this session before it can be updated
  * with writer_servers/calendar_id configured (cloud: riley@cheek.org's connector), every
    write goes through that connector to Paul's calendar by explicit id, never "primary"

What a guarded session may never touch (see protected()):
  * the guard's state and config, by any mention, in any tool
  * the guard's own code, the memory repo's .claude/, .gitignore and .gitattributes, by
    any write (Write/Edit, redirects, cp/mv/rm/sed -i and friends, inline interpreters)
  * git: no force-add, no staging of state or config, no force-push, no checkout/rm/reset
    of protected files

A session is guarded when its prompt invokes calendar-manager, when it runs inside the
memory repo (a .calendar-manager-memory marker), or when the tool call comes from one of
the plugin's agents.

Nothing an agent learns can loosen this. The guard reads only its config (an env var or a
file outside anything the agents commit), which the agents are not allowed to touch.

Stdlib only. Exit 0 always; a deny is a JSON permissionDecision on stdout.
"""
import datetime as dt
import json
import os
import re
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_paths  # noqa: E402

SCRIPT_DIR = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(SCRIPT_DIR)

# Set per hook call by init_paths(), from the event's cwd.
HOME = STATE = GUARDED_DIR = SOLO_DIR = CREATED = CONFIG = HOME_CONFIG = ""


def init_paths(cwd=None):
    global HOME, STATE, GUARDED_DIR, SOLO_DIR, CREATED, CONFIG, HOME_CONFIG
    p = cm_paths.paths(cwd)
    HOME, STATE, CONFIG, HOME_CONFIG = p["home"], p["state"], p["config"], p["home_config"]
    GUARDED_DIR = os.path.join(STATE, "guarded")
    SOLO_DIR = os.path.join(STATE, "solo_seen")
    CREATED = os.path.join(STATE, "created_events.json")


init_paths()

SOLO_TTL = 30 * 60
MARKER_TTL = 14 * 24 * 3600
RUN_PROMPT = re.compile(
    r"(^|[\s/])calendar-manager:|(^|\s)/calendar-(run|guidance|promote-guidance|schedule)\b",
    re.I)
AGENT_NAMES = {
    "conflict-scanner", "commute-planner", "travel-planner",
    "categorizer", "notes-reviewer", "one-on-one-auditor",
    "invite-reconciler", "offered-times-tracker",
}

DEFAULT_CONFIG = {
    "owner_emails": ["paul@cheek.org", "pcheek@mit.edu"],
    "owner_calendars": ["primary"],
    "callie_email": "calliemcheek@gmail.com",
    "travel_color_ids": ["1"],
    "home_timezone": "America/New_York",
    # Write identity. Empty = write through any calendar connector to "primary" (desktop).
    "calendar_id": "",          # e.g. paul@cheek.org: every write must name it explicitly
    "writer_servers": [],       # e.g. ["org-connector-google_calendar"] (riley@cheek.org)
    "agent_identity": "",       # e.g. riley@cheek.org: events it created are agent-made
}

# Calendar MCP actions a guarded session may call. Anything else on a calendar server
# (delete_event, respond_to_event, and whatever a future connector adds) is denied.
CAL_READ = re.compile(r"^(list|get|search|suggest|query|find|freebusy|free_busy)")
CAL_ALLOWED_WRITES = {"create_event", "update_event"}

# update_event keys that are fine on any event, guests or not.
UPDATE_ANY = {"eventId", "calendarId", "colorId", "availability", "notificationLevel"}
# keys that are never allowed on update.
UPDATE_NEVER = {
    "addedAttendeeEmails", "removedAttendeeEmails", "addGoogleMeetUrl",
    "googleMeetUrl", "guestPermissions", "conferenceData",
}

MESSAGE_SEND = re.compile(r"(^|_)(send_message|reply|forward|schedule_message)$")
RAW_CAL_API = re.compile(
    r"googleapis\.com/(batch/)?calendar|calendar/v3|calendarmcp\.googleapis|gcalcli",
    re.I,
)
TRAVEL_TIMED = ("flight:", "train:", "bus:", "drive:")
HAS_OFFSET = re.compile(r"T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- helpers

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def config():
    cfg = cm_paths.load_config(CONFIG, DEFAULT_CONFIG)
    cfg["owner_emails"] = [e.lower() for e in cfg["owner_emails"]]
    cfg["owner_calendars"] = [c.lower() for c in cfg["owner_calendars"]] + ["primary"]
    cfg["callie_email"] = cfg["callie_email"].lower()
    cfg["travel_color_ids"] = [str(c) for c in cfg["travel_color_ids"]]
    cfg["calendar_id"] = str(cfg.get("calendar_id") or "").lower()
    cfg["writer_servers"] = [str(w).lower() for w in cfg.get("writer_servers") or []]
    cfg["agent_identity"] = str(cfg.get("agent_identity") or "").lower()
    if cfg["agent_identity"]:
        cfg["owner_emails"] = cfg["owner_emails"] + [cfg["agent_identity"]]
    return cfg


def now_utc():
    override = os.environ.get("CALENDAR_MANAGER_NOW")  # tests only
    if override:
        t = parse_time(override)
        if t is not None and t.tzinfo is not None:
            return t
    return dt.datetime.now(dt.timezone.utc)


def is_past(start, all_day, cfg):
    """True when an event starting at `start` has already begun. Unreadable counts as past:
    the guard never edits what it can't place in time."""
    if not start:
        return True
    start = str(start)
    if all_day or DATE_ONLY.match(start):
        try:
            from zoneinfo import ZoneInfo
            today = now_utc().astimezone(ZoneInfo(cfg.get("home_timezone") or
                                                  "America/New_York")).date()
            return dt.date.fromisoformat(start[:10]) < today
        except Exception:
            return True
    t = parse_time(start)
    if t is None or t.tzinfo is None:
        return True
    return t < now_utc()


def safe_id(session_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or ""))[:200]


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "calendar-manager guard: " + reason
            + " Do not retry or work around this. Log it as a question for Paul with"
            " `guidance.py ask` and move on.",
        }
    }))
    sys.exit(0)


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(v)
    except ValueError:
        return None


def minutes_between(start, end):
    a, b = parse_time(start), parse_time(end)
    if a is None or b is None:
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        return None
    return (b - a).total_seconds() / 60.0


# ---------------------------------------------------------------- guarded state

def is_guarded(event):
    agent = str(event.get("agent_type") or event.get("agent_name") or "")
    if agent.lower().startswith("calendar-manager:") or agent in AGENT_NAMES:
        return True
    for start in (event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        if cm_paths.find_marker(start):
            return True
    sid = safe_id(event.get("session_id"))
    return bool(sid) and os.path.exists(os.path.join(GUARDED_DIR, sid))


def mark_guarded(session_id):
    sid = safe_id(session_id)
    if not sid:
        return
    os.makedirs(GUARDED_DIR, exist_ok=True)
    with open(os.path.join(GUARDED_DIR, sid), "w", encoding="utf-8") as fh:
        fh.write(str(int(time.time())))
    now = time.time()
    for name in os.listdir(GUARDED_DIR):
        path = os.path.join(GUARDED_DIR, name)
        try:
            if now - os.path.getmtime(path) > MARKER_TTL:
                os.remove(path)
        except OSError:
            pass


def seen_event(session_id, event_id):
    """What this guard knows about an event: one the agents created, or one a read in this
    session returned within the last 30 minutes. None if neither."""
    if not event_id:
        return None
    created = load_json(CREATED, {})
    if event_id in created:
        return dict(created[event_id], solo=True, agent_created=True)
    seen = load_json(os.path.join(SOLO_DIR, safe_id(session_id) + ".json"), {})
    rec = seen.get(event_id)
    if rec and time.time() - rec.get("seen_at", 0) <= SOLO_TTL:
        return rec
    return None


def known_event(session_id, event_id):
    """An event the agents may fully edit: solo, or created by the agents (by this
    session's ledger, or by agent_identity per the event's creator)."""
    rec = seen_event(session_id, event_id)
    if rec and (rec.get("solo", True) or rec.get("agent_created")):
        return rec
    return None


# ---------------------------------------------------------------- the Callie exception

def guest_emails(items):
    out = []
    for item in items or []:
        if isinstance(item, dict):
            if item.get("resource"):
                out.append("<resource>")
                continue
            out.append(str(item.get("email", "")).strip().lower())
        else:
            out.append(str(item).strip().lower())
    return out


def others(emails, cfg):
    return {e for e in emails if e and e not in cfg["owner_emails"]}


def callie_ok(ev, cfg):
    """True when ev (summary, colorId, allDay, start, end) is a travel event Callie
    may be invited to: a flight, train or bus ride, a drive over 60 minutes, or an
    all-day Travel: event. Never a commute or a short drive."""
    summary = str(ev.get("summary") or "").strip()
    low = summary.lower()
    if str(ev.get("colorId") or "") not in cfg["travel_color_ids"]:
        return False, "Callie invites need the travel color"
    if "commute" in low or "drive time" in low:
        return False, "Callie is never invited to commutes or drive time"
    if ev.get("allDay"):
        if low.startswith("travel:"):
            return True, ""
        return False, "an all-day Callie event must be titled 'Travel: <place>'"
    if not low.startswith(TRAVEL_TIMED):
        return False, "Callie invites are for 'Flight:', 'Train:', 'Bus:' or 'Drive:' events only"
    if low.startswith("drive:"):
        mins = minutes_between(ev.get("start"), ev.get("end"))
        if mins is None:
            return False, "could not read the drive's start and end times"
        if mins <= 60:
            return False, "Callie is only invited to drives longer than an hour"
    return True, ""


# ---------------------------------------------------------------- PreToolUse checks

def check_times(tool_input):
    """Strict time zones: Paul lives in Boston but is often elsewhere, so a time without an
    explicit offset is a guess. Every timed start/end must carry one, and a timeZone field
    (which the connector applies over both offsets) must agree with them."""
    all_day = bool(tool_input.get("allDay"))
    times = [(k, tool_input.get(k)) for k in ("startTime", "endTime")
             if tool_input.get(k) not in (None, "")]
    for key, value in times:
        value = str(value).strip()
        if all_day and DATE_ONLY.match(value):
            continue
        if not HAS_OFFSET.search(value):
            deny("%s %r has no UTC offset. Build it with `tz.py to-iso \"<wall time>\" --zone "
                 "<IANA zone>` for wherever the event happens." % (key, value))
    zone_name = tool_input.get("timeZone")
    if not zone_name or all_day:
        return
    try:
        from zoneinfo import ZoneInfo
        if "/" not in str(zone_name) and zone_name != "UTC":
            raise ValueError("abbreviation")
        tz = ZoneInfo(str(zone_name))
    except Exception:
        deny("timeZone %r is not an IANA zone name (use e.g. Europe/London, never EST/GMT)."
             % zone_name)
    for key, value in times:
        t = parse_time(str(value))
        if t is None or t.tzinfo is None:
            deny("could not read %s %r." % (key, value))
        local = t.replace(tzinfo=None).replace(tzinfo=tz)
        if local.utcoffset() != t.utcoffset():
            deny("%s %r does not match timeZone %s, and the connector would apply %s over the "
                 "offset. For events that cross zones (flights), leave timeZone out and keep "
                 "each end's own offset." % (key, value, zone_name, zone_name))


def check_calendar_id(tool_input, cfg):
    if cfg["calendar_id"]:
        cal = str(tool_input.get("calendarId") or "").lower()
        if cal != cfg["calendar_id"]:
            deny("every write must name Paul's calendar explicitly: calendarId \"%s\" (got %r). "
                 "Through riley@cheek.org's connector, \"primary\" is Riley's own calendar."
                 % (cfg["calendar_id"], cal or "(none)"))
        return
    cal = str(tool_input.get("calendarId") or "primary").lower()
    if cal not in cfg["owner_calendars"]:
        deny("events may only be written to Paul's own calendar (got calendarId %r)." % cal)


def check_writer(server, cfg):
    if cfg["writer_servers"] and server not in cfg["writer_servers"]:
        deny("calendar writes go only through %s, so they show as created by %s. Use that "
             "connector with calendarId \"%s\"." % (", ".join(cfg["writer_servers"]),
                                                  cfg["agent_identity"] or "the agent account",
                                                  cfg["calendar_id"] or "primary"))


CREATE_TYPES = {"", "EVENT_TYPE_UNSPECIFIED", "DEFAULT", "WORKING_LOCATION", "OUT_OF_OFFICE"}
OOO_MAX = 14 * 3600  # one night outside 7am to 8pm local is 11 hours; never a whole trip


def check_event_type(tool_input):
    """Working-location and out-of-office entries are Paul's alone: no guests, timed OOO only.

    Riley's connector creates OOO with autoDeclineMode declineNone (verified 2026-10-03), so
    an OOO entry never declines anything; the agents still never RSVP."""
    kind = str(tool_input.get("eventType") or "").upper()
    if kind not in CREATE_TYPES:
        deny("eventType %s is not allowed; agents create regular events, working locations "
             "and out-of-office entries only." % kind)
    if kind not in ("WORKING_LOCATION", "OUT_OF_OFFICE"):
        return
    if guest_emails(tool_input.get("attendees")) or guest_emails(tool_input.get("attendeeEmails")):
        deny("working-location and out-of-office entries never have guests, Callie included.")
    if kind == "WORKING_LOCATION" and not tool_input.get("workingLocationProperties"):
        deny("a working-location entry needs workingLocationProperties (build it with "
             "calendar_call.py create --working-location <label>).")
    if kind == "OUT_OF_OFFICE":
        if tool_input.get("allDay"):
            deny("out-of-office entries are timed, never all-day.")
        span = minutes_between(tool_input.get("startTime"), tool_input.get("endTime"))
        if span is None:
            deny("out-of-office entries need timed startTime and endTime with offsets.")
        if span * 60 > OOO_MAX:
            deny("an out-of-office entry covers one night (at most 14 hours); build them with "
                 "presence.py ooo.")


def check_create(tool_input, cfg):
    check_calendar_id(tool_input, cfg)
    if not tool_input.get("startTime") or not tool_input.get("endTime"):
        deny("create_event needs both startTime and endTime.")
    check_times(tool_input)
    if is_past(tool_input.get("startTime"), tool_input.get("allDay"), cfg):
        deny("nothing is ever created in the past (start %s)." % tool_input.get("startTime"))
    if tool_input.get("addGoogleMeetUrl") or tool_input.get("googleMeetUrl") \
            or tool_input.get("conferenceData"):
        deny("no Google Meet links. Paul is Zoom-only and Meet implies guests.")
    check_event_type(tool_input)
    guests = others(guest_emails(tool_input.get("attendees"))
                    + guest_emails(tool_input.get("attendeeEmails")), cfg)
    if not guests:
        return
    if guests != {cfg["callie_email"]}:
        deny("creating events with guests is not allowed (%s)." % ", ".join(sorted(guests)))
    ok, why = callie_ok({
        "summary": tool_input.get("summary"),
        "colorId": tool_input.get("colorId"),
        "allDay": tool_input.get("allDay"),
        "start": tool_input.get("startTime"),
        "end": tool_input.get("endTime"),
    }, cfg)
    if not ok:
        deny(why + ".")


def check_update(tool_input, session_id, cfg):
    check_calendar_id(tool_input, cfg)
    event_id = tool_input.get("eventId")
    if not event_id:
        deny("update_event without an eventId.")
    check_times(tool_input)
    rec = seen_event(session_id, event_id)
    if rec is None:
        deny("read this event (get_event, list_events or search_events) in this session before "
             "updating it, so the guard knows what it is and when it is.")
    if is_past(rec.get("start"), rec.get("allDay"), cfg):
        deny("past events are never edited (this one started %s)." % rec.get("start"))
    if tool_input.get("startTime") and is_past(tool_input["startTime"],
                                               tool_input.get("allDay"), cfg):
        deny("an event is never moved into the past (new start %s)." % tool_input["startTime"])
    for key in UPDATE_NEVER:
        if tool_input.get(key):
            deny("%s is never allowed: agents do not change guests or conferencing." % key)

    added = others(guest_emails(tool_input.get("addedAttendees")), cfg)
    adding_callie = False
    if added:
        if added != {cfg["callie_email"]}:
            deny("adding guests is not allowed (%s)." % ", ".join(sorted(added)))
        solo = known_event(session_id, event_id)
        if solo is None:
            deny("Callie can only be added to a solo event; read it with get_event first.")
        merged = dict(solo)
        for src, dst in (("summary", "summary"), ("colorId", "colorId"), ("allDay", "allDay"),
                         ("startTime", "start"), ("endTime", "end")):
            if tool_input.get(src) not in (None, ""):
                merged[dst] = tool_input[src]
        ok, why = callie_ok(merged, cfg)
        if not ok:
            deny(why + ".")
        adding_callie = True

    level = str(tool_input.get("notificationLevel") or "")
    if not adding_callie and level != "NONE":
        deny("set notificationLevel to \"NONE\" on every update so nobody is emailed.")

    extra = {k for k, v in tool_input.items()
             if k not in UPDATE_ANY and k != "addedAttendees" and v not in (None, "", [], {})}
    if extra and known_event(session_id, event_id) is None:
        deny("only colorId and availability may change on this event. Changing %s needs an "
             "event that is solo: one the agents created, or one get_event showed has no guests "
             "in the last 30 minutes." % ", ".join(sorted(extra)))


def check_pre(event, cfg):
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        deny("unreadable tool input.")
    low = tool.lower()

    if low.startswith("mcp__") and "calendar" in low.split("__")[1]:
        action = low.rsplit("__", 1)[-1]
        if CAL_READ.match(action):
            return
        if action not in CAL_ALLOWED_WRITES:
            deny("%s is not allowed. Agents never delete events, RSVP, decline, or change "
                 "calendars." % action)
        check_writer(low.split("__")[1], cfg)
        if action == "create_event":
            check_create(tool_input, cfg)
        else:
            check_update(tool_input, event.get("session_id"), cfg)
        return

    if low.startswith("mcp__") and ("gmail" in low or "slack" in low):
        action = low.rsplit("__", 1)[-1]
        if MESSAGE_SEND.search(action):
            deny("agents never message people. Draft it or ask Paul.")
        return

    if tool in ("Bash", "WebFetch"):
        text = json.dumps(tool_input)
        if RAW_CAL_API.search(text):
            deny("no raw Calendar API calls; use the calendar connector so the guard can see "
                 "what changes.")
        if tool == "Bash":
            check_bash(str(tool_input.get("command") or ""), event.get("cwd") or os.getcwd())
        return

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        tier = path_tier(resolve(raw, event.get("cwd") or os.getcwd()))
        if tier or raw.endswith(("guard.py", os.path.join("hooks", "hooks.json"))):
            deny("the guard's state, config and code, and the memory repo's .claude/, "
                 ".gitignore and .gitattributes, are off limits.")


# ---------------------------------------------------------------- protected paths

WRITERS = {"cp", "mv", "rm", "tee", "ln", "chmod", "chown", "truncate", "dd", "rsync",
           "install", "patch", "touch", "mkdir", "rmdir", "unlink", "shred", "sponge"}
INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "bash", "sh", "zsh"}
INLINE_FLAGS = {"-c", "-e", "--eval", "--command"}
SHELL_OPS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
GIT_STAGE_PATHS = {"add", "stage", "commit", "checkout", "restore", "rm", "mv", "reset",
                   "apply", "am", "update-index", "stash", "clean"}
FORCE_PUSH = {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror",
              "--delete", "-d", "--prune"}
SECRET_ENV = re.compile(r"CALENDAR_MANAGER_(CONFIG|STATE)")


def protected():
    """(hidden, code): hidden paths may not be mentioned at all; code paths may not be
    written. Both are real, resolved paths."""
    hidden = {os.path.realpath(STATE), os.path.realpath(CONFIG), os.path.realpath(HOME_CONFIG)}
    code = {os.path.join(HOME, ".claude"), os.path.join(HOME, ".gitignore"),
            os.path.join(HOME, ".gitattributes"), os.path.join(HOME, cm_paths.MARKER),
            SCRIPT_DIR, os.path.join(PLUGIN_ROOT, "hooks")}
    return hidden, {os.path.realpath(c) for c in code}


def resolve(token, cwd):
    t = os.path.expandvars(os.path.expanduser(token.strip()))
    if not t:
        return ""
    if not os.path.isabs(t):
        t = os.path.join(cwd, t)
    return os.path.realpath(t)


def inside(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def path_tier(path):
    if not path:
        return None
    hidden, code = protected()
    if inside(path, hidden):
        return "hidden"
    if inside(path, code):
        return "code"
    return None


def path_forms(path):
    """Spellings of an absolute path a command might use."""
    forms = {path}
    home = os.path.expanduser("~")
    if path.startswith(home + os.sep):
        rest = path[len(home):]
        forms |= {"~" + rest, "$HOME" + rest, "${HOME}" + rest}
    return forms


def lex(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def segments(tokens):
    seg = []
    for tok in tokens:
        if tok in SHELL_OPS:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def candidates(token):
    out = [token]
    if "=" in token:
        out.append(token.split("=", 1)[1])
    return [c for c in out if c and not c.startswith("-")] or []


def check_bash(command, cwd):
    hidden, code = protected()
    # 1. hidden paths: any spelling, anywhere in the command, or the env vars that name them
    for p in hidden:
        for form in path_forms(p):
            if form in command:
                deny("the guard's state and config are off limits.")
    if SECRET_ENV.search(command):
        deny("the guard's config and state are off limits.")
    try:
        tokens = lex(command)
    except ValueError:
        deny("could not parse this command; split it into simpler commands.")
    for seg in segments(tokens):
        argv, targets = [], []
        i = 0
        while i < len(seg):
            tok = seg[i]
            if tok in REDIRECTS or re.fullmatch(r"\d?>{1,2}\|?", tok):
                if i + 1 < len(seg):
                    targets.append(seg[i + 1])
                i += 2
                continue
            argv.append(tok)
            i += 1
        tiers = [path_tier(resolve(c, cwd)) for tok in argv for c in candidates(tok)]
        if "hidden" in tiers:
            deny("the guard's state and config are off limits.")
        for t in targets:
            if path_tier(resolve(t, cwd)):
                deny("writing to the guard's files or the memory repo's .claude/, .gitignore "
                     "or .gitattributes is not allowed.")
        if not argv:
            continue
        prog = os.path.basename(argv[0])
        if prog == "sudo" and len(argv) > 1:
            argv, prog = argv[1:], os.path.basename(argv[1])
        if prog in WRITERS or (prog == "sed" and any(a.startswith("-i") or a == "--in-place"
                                                       for a in argv)):
            if "code" in tiers:
                deny("%s on the guard's code or the memory repo's .claude/, .gitignore or "
                     ".gitattributes is not allowed." % prog)
        if re.sub(r"[\d.]+$", "", prog) in INTERPRETERS and \
                any(a in INLINE_FLAGS for a in argv[1:]):
            inline = " ".join(argv)
            names = (".gitignore", ".gitattributes", ".claude", "guard.py", "hooks.json")
            if any(form in inline for p in code for form in path_forms(p)) or \
                    any(n in inline for n in names):
                deny("inline code may not touch the guard's code or the memory repo's "
                     "protected files.")
        if prog == "git":
            check_git(argv, cwd)


def check_git(argv, cwd):
    args = argv[1:]
    while args and args[0].startswith("-"):  # global options: -C dir, -c k=v, --no-pager
        if args[0] == "-C" and len(args) > 1:
            cwd = resolve(args[1], cwd)
            args = args[2:]
        elif args[0] == "-c" and len(args) > 1:
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return
    sub, rest = args[0], args[1:]
    if sub == "push":
        bad = [a for a in rest if a in FORCE_PUSH or a.startswith("--force")
               or (not a.startswith("-") and (a.startswith("+") or a.startswith(":")))]
        if bad:
            deny("never force-push or delete remote branches (%s). On a rejected push, "
                 "`git pull --rebase` and push again." % " ".join(bad))
        return
    if sub not in GIT_STAGE_PATHS:
        return
    if sub in ("add", "stage") and any(a in ("-f", "--force") or
                                       (a.startswith("-") and not a.startswith("--")
                                        and "f" in a[1:]) for a in rest):
        deny("git add --force would stage ignored files such as the guard's state.")
    for a in rest:
        if a.startswith("-"):
            continue
        low = a.lower()
        if path_tier(resolve(a, cwd)) or re.search(r"(^|/)state(/|$)|config\.json", low):
            deny("git %s may not touch the guard's state, config or protected files (%s)."
                 % (sub, a))


# ---------------------------------------------------------------- PostToolUse recording

def event_dicts(obj, depth=0):
    """Every dict in a tool response that looks like a calendar event."""
    if depth > 6:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if s[:1] in "[{":
            try:
                yield from event_dicts(json.loads(s), depth + 1)
            except ValueError:
                pass
        return
    if isinstance(obj, list):
        for item in obj:
            yield from event_dicts(item, depth + 1)
        return
    if isinstance(obj, dict):
        if obj.get("id") and ("start" in obj or "summary" in obj):
            yield obj
        for key, value in obj.items():
            if key not in ("start", "end", "attendees", "organizer", "creator"):
                yield from event_dicts(value, depth + 1)


def details(ev):
    start, end = ev.get("start") or {}, ev.get("end") or {}
    if not isinstance(start, dict):
        start = {"dateTime": start}
    if not isinstance(end, dict):
        end = {"dateTime": end}
    return {
        "summary": ev.get("summary", ""),
        "colorId": str(ev.get("colorId") or ""),
        "allDay": "date" in start and "dateTime" not in start,
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
    }


def is_solo(ev, cfg):
    organizer = ev.get("organizer") or {}
    if isinstance(organizer, dict) and organizer.get("email") and not organizer.get("self") \
            and organizer["email"].lower() not in cfg["owner_emails"]:
        return False
    for a in ev.get("attendees") or []:
        if not isinstance(a, dict) or a.get("self") or a.get("resource"):
            continue
        if str(a.get("email", "")).lower() not in cfg["owner_emails"]:
            return False
    return True


def record_post(event, cfg):
    tool = str(event.get("tool_name") or "").lower()
    if not tool.startswith("mcp__") or "calendar" not in tool.split("__")[1]:
        return
    action = tool.rsplit("__", 1)[-1]
    events = list(event_dicts(event.get("tool_response")))
    now = time.time()
    if action == "create_event":
        created = load_json(CREATED, {})
        for ev in events[:1]:
            rec = details(ev)
            rec["created_at"] = now
            created[ev["id"]] = rec
        save_json(CREATED, created)
    elif CAL_READ.match(action):
        path = os.path.join(SOLO_DIR, safe_id(event.get("session_id")) + ".json")
        seen = load_json(path, {})
        seen = {k: v for k, v in seen.items() if now - v.get("seen_at", 0) <= SOLO_TTL}
        for ev in events:
            rec = details(ev)
            rec["seen_at"] = now
            rec["solo"] = is_solo(ev, cfg)
            creator = ev.get("creator") or {}
            rec["creator"] = str(creator.get("email", "")).lower() if isinstance(creator, dict) \
                else ""
            rec["agent_created"] = bool(cfg["agent_identity"]) and \
                rec["creator"] == cfg["agent_identity"]
            seen[ev["id"]] = rec
        save_json(path, seen)


# ---------------------------------------------------------------- entry point

PHASE = ""


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except ValueError:
        # We cannot tell whose session this is. Block only the irreversible.
        if "delete_event" in raw:
            deny("unreadable hook input on a delete.")
        return
    if not isinstance(event, dict):
        return
    init_paths(event.get("cwd"))
    name = event.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "")
    global PHASE
    PHASE = name

    if name == "UserPromptSubmit":
        if RUN_PROMPT.search(str(event.get("prompt") or "")):
            mark_guarded(event.get("session_id"))
        return
    if not is_guarded(event):
        return
    cfg = config()
    if name == "PreToolUse":
        check_pre(event, cfg)
    elif name == "PostToolUse":
        try:
            record_post(event, cfg)
        except Exception as exc:  # recording is best effort; never break the run
            print("calendar-manager guard: could not record %s" % exc, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        # A crash while checking a tool call is a deny, not a pass.
        if PHASE == "PreToolUse":
            deny("internal error (%s)." % exc.__class__.__name__)
        print("calendar-manager guard: %r" % exc, file=sys.stderr)
