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

Nothing an agent learns can loosen this. The guard reads only config.json, which the
agents are not allowed to edit.

Stdlib only. Exit 0 always; a deny is a JSON permissionDecision on stdout.
"""
import datetime as dt
import json
import os
import re
import sys
import time

HOME = os.path.expanduser(os.environ.get("CALENDAR_MANAGER_HOME", "~/.claude/calendar-manager"))
STATE = os.path.join(HOME, "state")
GUARDED_DIR = os.path.join(STATE, "guarded")
SOLO_DIR = os.path.join(STATE, "solo_seen")
CREATED = os.path.join(STATE, "created_events.json")
CONFIG = os.path.join(HOME, "config.json")

SOLO_TTL = 30 * 60
MARKER_TTL = 14 * 24 * 3600
RUN_PROMPT = re.compile(r"(^|[\s/])calendar-manager:", re.I)
AGENT_NAMES = {
    "conflict-scanner", "commute-planner", "travel-planner",
    "categorizer", "notes-reviewer", "one-on-one-auditor",
}

DEFAULT_CONFIG = {
    "owner_emails": ["paul@cheek.org", "pcheek@mit.edu"],
    "owner_calendars": ["primary"],
    "callie_email": "calliemcheek@gmail.com",
    "travel_color_ids": ["1"],
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
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG, {}) or {})
    cfg["owner_emails"] = [e.lower() for e in cfg["owner_emails"]]
    cfg["owner_calendars"] = [c.lower() for c in cfg["owner_calendars"]] + ["primary"]
    cfg["callie_email"] = cfg["callie_email"].lower()
    cfg["travel_color_ids"] = [str(c) for c in cfg["travel_color_ids"]]
    return cfg


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


def known_event(session_id, event_id):
    """Details of an event this guard has verified to be solo, or None."""
    if not event_id:
        return None
    created = load_json(CREATED, {})
    if event_id in created:
        return created[event_id]
    seen = load_json(os.path.join(SOLO_DIR, safe_id(session_id) + ".json"), {})
    rec = seen.get(event_id)
    if rec and time.time() - rec.get("seen_at", 0) <= SOLO_TTL:
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

def check_calendar_id(tool_input, cfg):
    cal = str(tool_input.get("calendarId") or "primary").lower()
    if cal not in cfg["owner_calendars"]:
        deny("events may only be written to Paul's own calendar (got calendarId %r)." % cal)


def check_create(tool_input, cfg):
    check_calendar_id(tool_input, cfg)
    if tool_input.get("addGoogleMeetUrl") or tool_input.get("googleMeetUrl") \
            or tool_input.get("conferenceData"):
        deny("no Google Meet links. Paul is Zoom-only and Meet implies guests.")
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
    for key in UPDATE_NEVER:
        if tool_input.get(key):
            deny("%s is never allowed: agents do not change guests or conferencing." % key)

    added = others(guest_emails(tool_input.get("addedAttendees")), cfg)
    adding_callie = False
    if added:
        if added != {cfg["callie_email"]}:
            deny("adding guests is not allowed (%s)." % ", ".join(sorted(added)))
        rec = known_event(session_id, event_id)
        if rec is None:
            deny("Callie can only be added to a solo event; read it with get_event first.")
        merged = dict(rec)
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
        if tool == "Bash" and re.search(r"calendar-manager/(state|config\.json)|guard\.py|"
                                        r"hooks\.json", text):
            deny("the guard's state and config are off limits.")
        return

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = os.path.abspath(os.path.expanduser(str(
            tool_input.get("file_path") or tool_input.get("notebook_path") or "")))
        if path.startswith(STATE + os.sep) or path == CONFIG \
                or path.endswith(("guard.py", os.path.join("hooks", "hooks.json"))):
            deny("the guard's state, config and code are off limits.")


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
            if is_solo(ev, cfg):
                rec = details(ev)
                rec["seen_at"] = now
                seen[ev["id"]] = rec
            else:
                seen.pop(ev["id"], None)
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
