#!/usr/bin/env python3
"""Read and set Paul's Google Calendar working location (home, office, or a named place).

The calendar MCP connectors cannot do this: their update_event has no
workingLocationProperties field, so an existing working-location entry (the recurring
all-day "Home", or a partial-day one) can't be retyped or relabeled through them. This
script reaches the Calendar API through the working-location relay instead
(`relay/working-location-relay.gs`), a Google Apps Script web app that runs as
riley@cheek.org and edits nothing but Paul's working-location entries. The agents never
hold a Calendar credential: the relay key they use can do only what the relay allows.

    working_location.py list --date 2026-10-02
    working_location.py set  --event-id ID --type custom --label "MIT (E66, Cambridge)"
                             [--start 2026-10-02T09:00:00-04:00 --end 2026-10-02T15:30:00-04:00]
    working_location.py add  --start ISO --end ISO --type custom --label "Babson Boston"
    working_location.py add  --date 2026-10-09 --type home          (all-day)

Needs CALENDAR_MANAGER_WL_RELAY_URL and CALENDAR_MANAGER_WL_RELAY_KEY in the environment,
and script.google.com plus script.googleusercontent.com on the network allowlist.

The relay is the authority: it reads each event and refuses anything that isn't a
current or future workingLocation entry on Paul's calendar, sends only working-location
fields and start/end, and never notifies anyone. This script checks the same things
before sending, so mistakes fail fast with a clear message. Config
"working_location_relay": false switches it off.

Exit codes: 0 ok, 2 refused (the reason is on stderr), 3 relay or network error.
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
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_paths  # noqa: E402

HAS_OFFSET = re.compile(r"T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPES = ("home", "office", "custom")
DEFAULTS = {"home_timezone": "America/New_York", "working_location_relay": True}


class Refused(Exception):
    pass


def config():
    p = cm_paths.paths()
    return cm_paths.load_config(p["config"], DEFAULTS)


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


# ---------------------------------------------------------------- relay

def relay(payload):
    url = os.environ.get("CALENDAR_MANAGER_WL_RELAY_URL")
    key = os.environ.get("CALENDAR_MANAGER_WL_RELAY_KEY")
    if not url or not key:
        raise Refused("the working-location relay isn't set up: CALENDAR_MANAGER_WL_RELAY_URL "
                      "and CALENDAR_MANAGER_WL_RELAY_KEY are missing from the environment. "
                      "See relay/working-location-relay.gs.")
    body = json.dumps(dict(payload, key=key)).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    try:
        # Apps Script answers a POST with a redirect to a GET; urllib follows it.
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("relay -> HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
    except urllib.error.URLError as e:
        raise RuntimeError("relay unreachable: %s (is script.google.com on the network "
                           "allowlist?)" % e.reason)
    try:
        res = json.loads(raw)
    except ValueError:
        raise RuntimeError("relay sent something that isn't JSON (a Google sign-in page means "
                           "the web app isn't deployed with access 'Anyone'): %r" % raw[:200])
    if res.get("refused"):
        raise Refused("relay: " + str(res["refused"]))
    if not res.get("ok"):
        raise RuntimeError("relay: " + str(res.get("error") or res))
    res.pop("ok", None)
    return res


# ---------------------------------------------------------------- checks

def check_type(kind, label):
    if kind not in TYPES:
        raise Refused("--type must be home, office or custom (got %r)." % kind)
    if kind != "home" and not label:
        raise Refused("--type %s needs a --label naming the place." % kind)


def time_fields(args, cfg, required):
    if args.date:
        if args.start or args.end:
            raise Refused("use either --date (all-day) or --start/--end, not both.")
        if not DATE_ONLY.match(args.date):
            raise Refused("--date must be YYYY-MM-DD.")
        if dt.date.fromisoformat(args.date) < today_local(cfg):
            raise Refused("%s is in the past." % args.date)
        return {"date": args.date}
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
    return {"start": args.start, "end": args.end}


# ---------------------------------------------------------------- commands

def cmd_list(args, cfg):
    if not DATE_ONLY.match(args.date or ""):
        raise Refused("--date must be YYYY-MM-DD.")
    print(json.dumps(relay({"op": "list", "date": args.date}).get("items", []), indent=1))


def cmd_set(args, cfg):
    check_type(args.type, args.label)
    if args.date:
        raise Refused("set takes --start/--end to retime, not --date.")
    payload = {"op": "set", "eventId": args.event_id, "type": args.type, "label": args.label}
    payload.update(time_fields(args, cfg, required=False))
    print(json.dumps(relay(payload)))


def cmd_add(args, cfg):
    check_type(args.type, args.label)
    payload = {"op": "add", "type": args.type, "label": args.label}
    payload.update(time_fields(args, cfg, required=True))
    print(json.dumps(relay(payload)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--date", required=True)
    for name in ("set", "add"):
        p = sub.add_parser(name)
        if name == "set":
            p.add_argument("--event-id", required=True)
        p.add_argument("--type", required=True, choices=TYPES)
        p.add_argument("--label", default="")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--date")
    args = ap.parse_args(argv)
    cfg = config()
    if cfg.get("working_location_relay") is False:
        print("refused: working_location_relay is off in the calendar-manager config.",
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
