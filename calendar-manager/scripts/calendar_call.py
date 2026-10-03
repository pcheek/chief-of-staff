#!/usr/bin/env python3
"""Build and check calendar tool inputs, so no agent ever types a time by hand.

The guard refuses any timed startTime/endTime without an explicit UTC offset. Models
asked to "build it with tz.py" still sometimes type `2026-10-05T08:30:00`. This script
makes the safe path the easy one: it emits the exact JSON to pass to create_event or
update_event, with every time built by tz.py's own localize(), and it checks any input
before it is sent.

    calendar_call.py create --zone America/New_York --start "2026-10-05 08:30" \
        --end "2026-10-05 09:00" --summary "HOLD: offered to Bob Toohey" --color 11 --busy
    calendar_call.py create --all-day --start 2026-10-11 --end 2026-10-12 --summary "NOTE: ..." \
        --color 11 --free
    calendar_call.py create --zone Asia/Singapore --start "2026-10-12 07:00" \
        --end "2026-10-12 20:00" --summary Singapore --working-location Singapore
    calendar_call.py create --zone Asia/Singapore --start "2026-10-12 20:00" \
        --end "2026-10-13 07:00" --summary "OOO: Singapore night (8pm to 7am local)" --ooo
    calendar_call.py times  --zone America/New_York --start "2026-10-05 08:30" --end "2026-10-05 09:00"
    calendar_call.py check  '<the JSON you are about to send>'      (or: check --file x.json)

`create` and `times` print JSON; paste it into the tool call unchanged (add eventId for an
update). `check` exits 0 when the input would pass the guard's time rules, 2 with one
line per problem otherwise. Every write's calendarId comes from the config, so the
Riley/Paul routing is never typed by hand either.

Exit codes: 0 ok, 2 refused (reasons on stderr). Stdlib only.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm_paths  # noqa: E402
import tz  # noqa: E402

DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULTS = {"calendar_id": "", "home_timezone": "America/New_York"}


class Refused(Exception):
    pass


def config():
    return cm_paths.load_config(cm_paths.paths()["config"], DEFAULTS)


def now_utc():
    override = os.environ.get("CALENDAR_MANAGER_NOW")  # tests only
    if override:
        return dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
    return dt.datetime.now(dt.timezone.utc)


def calendar_id(cfg):
    return cfg.get("calendar_id") or "primary"


def build_time(wall, zone_name):
    """'2026-10-05 08:30' in zone -> '2026-10-05T08:30:00-04:00', via tz.py itself."""
    try:
        return tz.localize(tz.parse_wall(wall), tz.zone(zone_name)).isoformat(timespec="seconds")
    except ValueError as exc:
        raise Refused("%s in %s: %s" % (wall, zone_name, exc))
    except (Exception, SystemExit) as exc:  # tz.py exits on an unknown zone or bad wall time
        raise Refused("can't build %r in zone %r: %s" % (wall, zone_name, exc))


def build_times(args):
    if not args.zone:
        raise Refused("--zone is required (the IANA zone where the event happens, from the "
                      "location timeline).")
    start, end = build_time(args.start, args.zone), build_time(args.end, args.zone)
    if tz.parse_iso(end) <= tz.parse_iso(start):
        raise Refused("end %s is not after start %s." % (end, start))
    return {"startTime": start, "endTime": end}


def cmd_times(args, cfg):
    out = build_times(args)
    problems = check_input(out, cfg, full_call=False)
    if problems:
        raise Refused("; ".join(problems))
    print(json.dumps(out))


def special(args):
    """--working-location / --ooo: Google's typed entries, which take fewer fields."""
    if args.working_location and args.ooo:
        raise Refused("an entry is either a working location or out of office, not both.")
    if not (args.working_location or args.ooo):
        return None
    extra = [n for n, v in (("--color", args.color), ("--busy/--free", args.busy or args.free),
                            ("--description", args.description), ("--location", args.location))
             if v]
    if extra:
        raise Refused("%s can't go on a working-location or out-of-office entry." % ", ".join(extra))
    if args.ooo:
        if args.all_day:
            raise Refused("out-of-office entries can't be all-day; give the timed window.")
        # No description or notificationLevel: the API refuses an OOO create carrying them.
        # Google makes these autoDeclineMode declineNone: they never decline anything.
        return {"eventType": "OUT_OF_OFFICE"}
    label = args.working_location.strip()
    if label.lower() == "home":
        props = {"type": "HOME_OFFICE"}
    else:
        props = {"type": "CUSTOM_LOCATION", "customLocationLabel": label}
    return {"eventType": "WORKING_LOCATION", "workingLocationProperties": props,
            "availability": "AVAILABILITY_FREE", "visibility": "public"}


def cmd_create(args, cfg):
    typed = special(args)
    body = {"calendarId": calendar_id(cfg), "summary": args.summary}
    if args.all_day:
        for v in (args.start, args.end):
            if not DATE_ONLY.match(v or ""):
                raise Refused("--all-day takes --start/--end as YYYY-MM-DD (end exclusive).")
        if args.end <= args.start:
            raise Refused("all-day --end must be after --start (it is exclusive).")
        body.update({"allDay": True, "startTime": args.start, "endTime": args.end})
    else:
        body.update(build_times(args))
    if args.color:
        body["colorId"] = str(args.color)
    if args.busy or args.free:
        body["availability"] = "AVAILABILITY_FREE" if args.free else "AVAILABILITY_BUSY"
    if args.description:
        body["description"] = args.description
    if args.location:
        body["location"] = args.location
    if typed:
        body.update(typed)
    else:
        body["notificationLevel"] = "NONE"
    problems = check_input(body, cfg)
    if problems:
        raise Refused("; ".join(problems))
    print(json.dumps(body))


def check_input(body, cfg, full_call=True):
    """The guard's time rules, plus calendarId routing on a full call. Returns problems."""
    problems = []
    want = calendar_id(cfg)
    if full_call and cfg.get("calendar_id") and str(body.get("calendarId", "")).lower() != want.lower():
        problems.append("calendarId must be %r (got %r)." % (want, body.get("calendarId")))
    all_day = bool(body.get("allDay"))
    times = {}
    for key in ("startTime", "endTime"):
        v = body.get(key)
        if v in (None, ""):
            continue
        v = str(v)
        if all_day or DATE_ONLY.match(v):
            if not DATE_ONLY.match(v):
                problems.append("%s %r: all-day times are YYYY-MM-DD." % (key, v))
            continue
        if not tz.OFFSET.search(v):
            problems.append("%s %r has no UTC offset. Rebuild it: calendar_call.py times "
                            "--zone <IANA zone> --start 'YYYY-MM-DD HH:MM' --end '...'." % (key, v))
            continue
        try:
            times[key] = tz.parse_iso(v)
        except ValueError:
            problems.append("%s %r is not a valid ISO time." % (key, v))
            continue
        zone_name = body.get("timeZone")
        if zone_name:
            try:
                z = tz.zone(zone_name)
                if times[key].astimezone(z).utcoffset() != times[key].utcoffset():
                    problems.append("%s %r disagrees with timeZone %s; drop timeZone and keep "
                                    "the offsets." % (key, v, zone_name))
            except (Exception, SystemExit):
                problems.append("timeZone %r is not a valid IANA zone." % zone_name)
    if "startTime" in times and "endTime" in times and times["endTime"] <= times["startTime"]:
        problems.append("endTime is not after startTime.")
    if "startTime" in times and times["startTime"] < now_utc():
        problems.append("startTime %s is in the past; nothing in the past is created or "
                        "moved." % body["startTime"])
    return problems


def cmd_check(args, cfg):
    raw = open(args.file, encoding="utf-8").read() if args.file else args.json
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        raise Refused("check takes the tool input as JSON.")
    bodies = body if isinstance(body, list) else [body]
    problems = []
    for i, b in enumerate(bodies):
        for p in check_input(b, cfg):
            problems.append(("call %d: " % (i + 1) if len(bodies) > 1 else "") + p)
    if problems:
        raise Refused("\n".join(problems))
    print("ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("create", "times"):
        p = sub.add_parser(name)
        p.add_argument("--zone")
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        if name == "create":
            p.add_argument("--summary", required=True)
            p.add_argument("--all-day", action="store_true")
            p.add_argument("--color")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--busy", action="store_true")
            g.add_argument("--free", action="store_true")
            p.add_argument("--description")
            p.add_argument("--location")
            p.add_argument("--working-location", metavar="LABEL",
                           help="a Google working-location entry for LABEL (Home, MIT, a city)")
            p.add_argument("--ooo", action="store_true",
                           help="a Google out-of-office entry (never declines)")
    p = sub.add_parser("check")
    p.add_argument("json", nargs="?")
    p.add_argument("--file")
    args = ap.parse_args(argv)
    cfg = config()
    try:
        {"create": cmd_create, "times": cmd_times, "check": cmd_check}[args.cmd](args, cfg)
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
