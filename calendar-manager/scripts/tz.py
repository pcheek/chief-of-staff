#!/usr/bin/env python3
"""calendar-manager time zone helper. Agents never do offset or DST math in their heads.

Paul is based in Boston (America/New_York) and often somewhere else. Every time an agent
writes, compares or reports goes through this script, so offsets and daylight-saving changes
come from the IANA database, not from memory.

    tz.py now [--zone Z]                       current time in Z and in Boston
    tz.py to-iso "2026-11-03 14:00" --zone Z   wall-clock time in Z -> ISO 8601 with offset
                                               (exit 2 if DST makes it ambiguous or nonexistent)
    tz.py convert ISO --to Z [--to Z2 ...]     an ISO time with offset, shown in other zones
    tz.py show ISO --local Z                   report format: "Tue Nov 3, 2:00pm GMT (9:00am Boston)"
    tz.py day-window --date 2026-11-03 --zone Z   start/end of that local day, ISO with offsets
    tz.py check ISO [ISO ...]                  exit 1 unless every time has an explicit offset
    tz.py zone-of "London"                     IANA zone for a city in references/timezones.md

Stdlib only (zoneinfo, Python 3.9+).
"""
import argparse
import datetime as dt
import os
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HOME_ZONE = "America/New_York"
OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
CITY_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills",
                          "calendar-sop", "references", "timezones.md")


def zone(name):
    # EST, GMT, CET and friends exist in the database as fixed offsets with no DST: refuse them.
    if "/" not in str(name) and name != "UTC":
        sys.exit("use a region/city IANA zone such as America/New_York, not %r" % name)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        sys.exit("unknown IANA time zone: %r (use names like Europe/London, not GMT or EST)" % name)


def parse_iso(value):
    v = value.strip()
    if not OFFSET.search(v):
        sys.exit("no UTC offset in %r: every time must carry one (e.g. -04:00)" % value)
    return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))


def parse_wall(value):
    v = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M%p", "%Y-%m-%d %I%p"):
        try:
            return dt.datetime.strptime(v.upper(), fmt)
        except ValueError:
            continue
    sys.exit("could not read %r; use 'YYYY-MM-DD HH:MM' (24h)" % value)


def localize(naive, tz):
    """Attach tz to a wall-clock time, refusing DST gaps and folds."""
    a = naive.replace(tzinfo=tz, fold=0)
    b = naive.replace(tzinfo=tz, fold=1)
    if a.utcoffset() != b.utcoffset():
        # In a fold (clock falls back) both are real; in a gap (springs forward) neither is.
        roundtrip = a.astimezone(dt.timezone.utc).astimezone(tz).replace(tzinfo=None)
        if roundtrip != naive:
            raise ValueError("%s does not exist in %s (clocks spring forward)" % (naive, tz.key))
        raise ValueError("%s happens twice in %s (clocks fall back); ask which" % (naive, tz.key))
    return a


def label(t, tz):
    s = t.astimezone(tz)
    hour = s.strftime("%I:%M%p").lstrip("0").lower()
    return "%s %s" % (hour, s.tzname())


def human(t, local_name):
    local = zone(local_name)
    s = t.astimezone(local)
    out = "%s, %s" % (s.strftime("%a %b %d").replace(" 0", " "), label(t, local))
    if local.key != HOME_ZONE:
        out += " (%s Boston)" % label(t, zone(HOME_ZONE)).rsplit(" ", 1)[0]
    return out


def cmd_now(a):
    t = dt.datetime.now(dt.timezone.utc)
    print(t.astimezone(zone(a.zone)).isoformat(timespec="seconds"), "|", human(t, a.zone))


def cmd_to_iso(a):
    try:
        print(localize(parse_wall(a.wall), zone(a.zone)).isoformat(timespec="seconds"))
    except ValueError as exc:
        print("AMBIGUOUS: %s" % exc)
        sys.exit(2)


def cmd_convert(a):
    t = parse_iso(a.iso)
    for z in a.to:
        print("%s  %s" % (t.astimezone(zone(z)).isoformat(timespec="seconds"), z))


def cmd_show(a):
    print(human(parse_iso(a.iso), a.local))


def cmd_day_window(a):
    d = dt.date.fromisoformat(a.date)
    tz = zone(a.zone)
    start = dt.datetime.combine(d, dt.time(0), tz)
    end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tz)
    print(start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))


def cmd_check(a):
    bad = [v for v in a.iso if not OFFSET.search(v.strip())]
    for v in bad:
        print("MISSING OFFSET: %s" % v)
    sys.exit(1 if bad else 0)


def cmd_zone_of(a):
    want = a.city.strip().lower()
    try:
        with open(CITY_TABLE, encoding="utf-8") as fh:
            for line in fh:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2 and "/" in cells[1]:
                    names = [n.strip().lower() for n in cells[0].split(",")]
                    if want in names:
                        print(cells[1])
                        return
    except OSError:
        pass
    print("UNKNOWN: %r is not in references/timezones.md; look it up and ask Paul to confirm"
          % a.city)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("now")
    p.add_argument("--zone", default=HOME_ZONE)
    p = sub.add_parser("to-iso")
    p.add_argument("wall")
    p.add_argument("--zone", required=True)
    p = sub.add_parser("convert")
    p.add_argument("iso")
    p.add_argument("--to", action="append", required=True)
    p = sub.add_parser("show")
    p.add_argument("iso")
    p.add_argument("--local", default=HOME_ZONE)
    p = sub.add_parser("day-window")
    p.add_argument("--date", required=True)
    p.add_argument("--zone", default=HOME_ZONE)
    p = sub.add_parser("check")
    p.add_argument("iso", nargs="+")
    p = sub.add_parser("zone-of")
    p.add_argument("city")
    a = ap.parse_args()
    {"now": cmd_now, "to-iso": cmd_to_iso, "convert": cmd_convert, "show": cmd_show,
     "day-window": cmd_day_window, "check": cmd_check, "zone-of": cmd_zone_of}[a.cmd](a)


if __name__ == "__main__":
    main()
