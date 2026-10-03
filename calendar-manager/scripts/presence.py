#!/usr/bin/env python3
"""Where Paul is, as calendar entries: out-of-office nights when he's in another time zone.

Paul's rule: away from Boston's time zone, every hour outside 7am to 8pm local is out of
office. This script turns a stay into the exact OOO create_event inputs, so no agent does
offset or date-line math by hand:

    presence.py ooo --zone Asia/Singapore --city Singapore --from 2026-10-10 --to 2026-10-18 \
        --arrive 2026-10-11T00:20:00+08:00 --depart 2026-10-17T21:00:00+08:00 \
        [--skip 2026-10-12T18:00:00+08:00/2026-10-13T08:00:00+08:00 ...]

- One window per night of the stay: 20:00 local on each date from --from to the day before
  --to, until 07:00 local the next morning.
- Clipped to after --arrive (landing plus buffer) and before --depart (leaving for the
  airport). Nights entirely outside the stay are dropped.
- --skip intervals (existing OOO entries, Paul's or the agents') are subtracted, so nothing
  is doubled. Pass every OOO already on the calendar in the stay.
- Nothing is printed for a zone whose UTC offset matches Boston's that night: Paul only
  wants OOO in other time zones (a Miami trip gets none).
- Windows already over are dropped; one that has started is trimmed to start now.

Prints a JSON list of create_event inputs (eventType OUT_OF_OFFICE, no description and no
notificationLevel: the calendar API refuses an OOO create that carries them). Google sets
these to autoDeclineMode declineNone, so they never decline anything. Pass each one
unchanged. Exit codes: 0 ok (an empty list is ok), 2 refused. Stdlib only.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_call as cc  # noqa: E402
import tz  # noqa: E402

DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DAY_START = dt.time(7, 0)
DAY_END = dt.time(20, 0)


class Refused(Exception):
    pass


def instant(name, value):
    if not value:
        return None
    if not tz.OFFSET.search(value):
        raise Refused("%s %r needs an explicit UTC offset." % (name, value))
    try:
        return tz.parse_iso(value)
    except ValueError:
        raise Refused("%s %r is not a valid ISO time." % (name, value))


def date_arg(name, value):
    if not DATE_ONLY.match(value or ""):
        raise Refused("%s must be YYYY-MM-DD (got %r)." % (name, value))
    return dt.date.fromisoformat(value)


def subtract(windows, cuts):
    """Remove each (start, end) in cuts from every window. All values are aware datetimes."""
    out = []
    for s, e in windows:
        pieces = [(s, e)]
        for cs, ce in cuts:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt
        out.extend(pieces)
    return out


def nights(zone_name, first, last, arrive=None, depart=None, skips=(), now=None):
    """OOO (start, end) pairs for a stay in zone_name, nights of first .. last-1."""
    z = tz.zone(zone_name)
    home = tz.zone(tz.HOME_ZONE)
    if last <= first:
        raise Refused("--to must be after --from (the departure date, after the arrival date).")
    windows = []
    d = first
    while d < last:
        start = tz.localize(dt.datetime.combine(d, DAY_END), z)
        end = tz.localize(dt.datetime.combine(d + dt.timedelta(days=1), DAY_START), z)
        if start.utcoffset() == start.astimezone(home).utcoffset():
            d += dt.timedelta(days=1)
            continue  # same clock as Boston that night: not another time zone
        if arrive and arrive > start:
            start = arrive
        if depart and depart < end:
            end = depart
        if end > start:
            windows.append((start, end))
        d += dt.timedelta(days=1)
    windows = subtract(windows, skips)
    if now:
        windows = [(max(s, now), e) for s, e in windows if e > now]
    # Under five minutes isn't worth an entry (a sliver left by a skip or by "now").
    return [(s, e) for s, e in windows if (e - s) >= dt.timedelta(minutes=5)]


def ceil_minute(t):
    if t.second or t.microsecond:
        t = t.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    return t


def cmd_ooo(args, cfg):
    first, last = date_arg("--from", args.date_from), date_arg("--to", args.date_to)
    arrive, depart = instant("--arrive", args.arrive), instant("--depart", args.depart)
    skips = []
    for raw in args.skip or []:
        if "/" not in raw:
            raise Refused("--skip takes START/END (two ISO times with offsets).")
        a, b = raw.split("/", 1)
        skips.append((instant("--skip start", a), instant("--skip end", b)))
    try:
        z = tz.zone(args.zone)
    except (Exception, SystemExit):
        raise Refused("--zone %r is not an IANA zone." % args.zone)
    city = args.city or args.zone.split("/")[-1].replace("_", " ")
    out = []
    for s, e in nights(args.zone, first, last, arrive, depart, skips, cc.now_utc()):
        s = ceil_minute(s).astimezone(z)
        e = e.astimezone(z)
        body = {"calendarId": cc.calendar_id(cfg),
                "summary": "OOO: %s night (8pm to 7am local)" % city,
                "startTime": s.isoformat(timespec="seconds"),
                "endTime": e.isoformat(timespec="seconds"),
                "eventType": "OUT_OF_OFFICE"}
        problems = cc.check_input(body, cfg)
        if problems:
            raise Refused("; ".join(problems))
        out.append(body)
    print(json.dumps(out, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ooo")
    p.add_argument("--zone", required=True)
    p.add_argument("--city")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--arrive")
    p.add_argument("--depart")
    p.add_argument("--skip", action="append")
    args = ap.parse_args(argv)
    try:
        cmd_ooo(args, cc.config())
    except (Refused, cc.Refused) as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
