#!/usr/bin/env python3
"""Read and set Paul's Google Calendar working location (home, office, or a named place).

The calendar MCP connectors cannot do this: their update_event has no
workingLocationProperties field, so an existing working-location entry (the recurring
all-day "Home", or a partial-day one) can't be retyped or relabeled through them. The
Calendar REST API can, and this script is the one sanctioned way a guarded session reaches
it. The guard still denies every other raw Calendar API call.

    working_location.py list --date 2026-10-02
    working_location.py set  --event-id ID --type custom --label "MIT (E66, Cambridge)"
                             [--start 2026-10-02T09:00:00-04:00 --end 2026-10-02T15:30:00-04:00]
    working_location.py add  --start ISO --end ISO --type custom --label "Babson Boston"
    working_location.py add  --date 2026-10-09 --type home          (all-day)

Writes go to the configured calendar_id (Paul's calendar) as Paul: in the cloud the
egress proxy injects his Google Calendar credentials on www.googleapis.com/calendar/, so
there is no token here. On a desktop, export CALENDAR_MANAGER_GCAL_TOKEN (an OAuth access
token with calendar.events scope) instead.

Enforced here, because this file is guard-protected code an agent cannot edit:
  * only events whose eventType is workingLocation are read or changed; nothing else
  * a set reads the event first and refuses one that has already ended, or a timed one
    that has already started (an all-day entry for today is fine: it is today's location)
  * only workingLocationProperties, and start/end on a timed entry, are ever sent
  * every timed start/end carries an explicit UTC offset
  * no guests, conferencing or notifications (sendUpdates=none)
  * entries this script creates carry extendedProperties.private.calendarManager=agent
  * config "working_location_rest": false switches the whole script off

Exit codes: 0 ok, 2 refused (the reason is on stderr), 3 API or network error.
Stdlib only.
"""
import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_paths  # noqa: E402

API = "https://www.googleapis.com/calendar/v3"
HAS_OFFSET = re.compile(r"T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPES = {"home": "homeOffice", "office": "officeLocation", "custom": "customLocation"}
DEFAULTS = {"calendar_id": "", "home_timezone": "America/New_York",
            "working_location_rest": True}


class Refused(Exception):
    pass


def config():
    p = cm_paths.paths()
    cfg = cm_paths.load_config(p["config"], DEFAULTS)
    cfg["calendar_id"] = str(cfg.get("calendar_id") or "primary")
    return cfg


def now_utc():
    override = os.environ.get("CALENDAR_MANAGER_NOW")  # tests only
    if override:
        return dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
    return dt.datetime.now(dt.timezone.utc)


def today_local(cfg):
    from zoneinfo import ZoneInfo
    return now_utc().astimezone(ZoneInfo(cfg["home_timezone"])).date()


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def need_offset(name, value):
    if not value or not HAS_OFFSET.search(value):
        raise Refused("%s %r needs an explicit UTC offset, e.g. 2026-10-02T09:00:00-04:00."
                      % (name, value))


# ---------------------------------------------------------------- HTTP

def request(method, path, body=None, query=None):
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    token = os.environ.get("CALENDAR_MANAGER_GCAL_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError("%s %s -> HTTP %s: %s" % (method, path, e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("%s %s -> %s" % (method, path, e.reason))
    return json.loads(raw) if raw else {}


def events_path(cfg, event_id=None):
    p = "/calendars/%s/events" % urllib.parse.quote(cfg["calendar_id"], safe="")
    return p + ("/" + urllib.parse.quote(event_id, safe="") if event_id else "")


# ---------------------------------------------------------------- body building

def properties(kind, label):
    if kind not in TYPES:
        raise Refused("--type must be home, office or custom (got %r)." % kind)
    t = TYPES[kind]
    if kind == "home":
        return {"type": t, "homeOffice": {}}
    if not label:
        raise Refused("--type %s needs a --label naming the place." % kind)
    if kind == "office":
        return {"type": t, "officeLocation": {"label": label}}
    return {"type": t, "customLocation": {"label": label}}


def summary_for(kind, label):
    return "Home" if kind == "home" else label


def check_event(ev, cfg):
    """Refuse anything but a current or future working-location entry."""
    if ev.get("eventType") != "workingLocation":
        raise Refused("event %s is a %r event, not a working location. This script only "
                      "touches working locations." % (ev.get("id"), ev.get("eventType")))
    start, end = ev.get("start") or {}, ev.get("end") or {}
    if "date" in start:
        last_day = dt.date.fromisoformat(end.get("date", start["date"])) - dt.timedelta(days=1)
        if last_day < today_local(cfg):
            raise Refused("event %s ended on %s; past entries are never edited."
                          % (ev.get("id"), last_day))
    else:
        if parse(start["dateTime"]) < now_utc():
            raise Refused("event %s started at %s; started entries are never edited. Add a "
                          "new partial-day entry for the rest of the day instead."
                          % (ev.get("id"), start["dateTime"]))


def time_fields(args, cfg, required):
    if args.date:
        if args.start or args.end:
            raise Refused("use either --date (all-day) or --start/--end, not both.")
        if not DATE_ONLY.match(args.date):
            raise Refused("--date must be YYYY-MM-DD.")
        day = dt.date.fromisoformat(args.date)
        if day < today_local(cfg):
            raise Refused("%s is in the past." % day)
        return {"start": {"date": day.isoformat()},
                "end": {"date": (day + dt.timedelta(days=1)).isoformat()}}
    if not (args.start or args.end):
        if required:
            raise Refused("give --start and --end (or --date for all day).")
        return {}
    need_offset("--start", args.start)
    need_offset("--end", args.end)
    s, e = parse(args.start), parse(args.end)
    if e <= s:
        raise Refused("--end must be after --start.")
    if s < now_utc():
        raise Refused("--start %s is in the past." % args.start)
    return {"start": {"dateTime": args.start}, "end": {"dateTime": args.end}}


# ---------------------------------------------------------------- commands

def cmd_list(args, cfg):
    if not DATE_ONLY.match(args.date or ""):
        raise Refused("--date must be YYYY-MM-DD.")
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(args.zone or cfg["home_timezone"])
    day = dt.date.fromisoformat(args.date)
    t0 = dt.datetime.combine(day, dt.time(0), tz)
    res = request("GET", events_path(cfg), query={
        "eventTypes": "workingLocation", "singleEvents": "true", "orderBy": "startTime",
        "timeMin": t0.isoformat(), "timeMax": (t0 + dt.timedelta(days=1)).isoformat()})
    out = []
    for ev in res.get("items", []):
        wl = ev.get("workingLocationProperties") or {}
        label = ((wl.get("customLocation") or wl.get("officeLocation") or {}).get("label")
                 or ("Home" if wl.get("type") == "homeOffice" else ""))
        out.append({"id": ev.get("id"), "start": ev.get("start"), "end": ev.get("end"),
                    "type": wl.get("type"), "label": label,
                    "recurring": bool(ev.get("recurringEventId")),
                    "agent": ((ev.get("extendedProperties") or {}).get("private") or {})
                    .get("calendarManager") == "agent"})
    print(json.dumps(out, indent=1))


def cmd_set(args, cfg):
    ev = request("GET", events_path(cfg, args.event_id))
    check_event(ev, cfg)
    body = {"workingLocationProperties": properties(args.type, args.label),
            "summary": summary_for(args.type, args.label)}
    times = time_fields(args, cfg, required=False)
    if times and "date" in (ev.get("start") or {}) and "dateTime" in times["start"]:
        raise Refused("event %s is all-day; add a partial-day entry instead of retiming it."
                      % args.event_id)
    body.update(times)
    res = request("PATCH", events_path(cfg, args.event_id), body, {"sendUpdates": "none"})
    print(json.dumps({"updated": res.get("id"), "summary": res.get("summary"),
                      "start": res.get("start"), "end": res.get("end"),
                      "workingLocationProperties": res.get("workingLocationProperties")}))


def cmd_add(args, cfg):
    body = {"eventType": "workingLocation", "visibility": "public",
            "transparency": "transparent",
            "summary": summary_for(args.type, args.label),
            "workingLocationProperties": properties(args.type, args.label),
            "extendedProperties": {"private": {"calendarManager": "agent"}}}
    body.update(time_fields(args, cfg, required=True))
    res = request("POST", events_path(cfg), body, {"sendUpdates": "none"})
    print(json.dumps({"created": res.get("id"), "summary": res.get("summary"),
                      "start": res.get("start"), "end": res.get("end")}))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--date", required=True)
    p.add_argument("--zone", help="IANA zone for the day (default: home_timezone)")
    for name in ("set", "add"):
        p = sub.add_parser(name)
        if name == "set":
            p.add_argument("--event-id", required=True)
        p.add_argument("--type", required=True, choices=sorted(TYPES))
        p.add_argument("--label", default="")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--date")
    args = ap.parse_args(argv)
    cfg = config()
    if cfg.get("working_location_rest") is False:
        print("refused: working_location_rest is off in the calendar-manager config.",
              file=sys.stderr)
        return 2
    try:
        {"list": cmd_list, "set": cmd_set, "add": cmd_add}[args.cmd](args, cfg)
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
