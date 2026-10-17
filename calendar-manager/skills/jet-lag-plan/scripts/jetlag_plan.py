#!/usr/bin/env python3
"""Circadian math for one trip. Python 3.9+, standard library only.

Usage: python3 jetlag_plan.py trip.json        (prints the plan as JSON)

trip.json:
{
  "dest_tz": "Europe/London",         # final destination
  "body_tz": "America/New_York",      # the zone his clock is on now (see SKILL.md step 3)
  "wake": "06:30", "bed": "22:30",    # habitual times; same wall clock at home and away
  "legs": [{"from": "BOS", "to": "LHR",
            "dep": "2026-11-02T21:55", "dep_tz": "America/New_York",
            "arr": "2026-11-03T09:45", "arr_tz": "Europe/London"}]
}
Exits 2 with a message on bad input.

Output: `events[]` is the Sleep/Awake timeline the skill writes to the calendar, in time
order. It covers the flights and layovers only: no pre-trip or post-landing blocks.
Everything else is the evidence the descriptions are written from.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ADV_RATE = 1.0         # h/day the clock advances with timed light (Eastman & Burgess 2009)
DEL_RATE = 1.5         # h/day it delays; delaying is easier, so it is the faster rate
MAX_ADVANCE = 8        # eastward shifts above 8h go the long way round, as a delay
CBT_BEFORE_WAKE = 2.0  # core body temperature minimum (CBTmin) sits ~2h before habitual wake
LIGHT_WINDOW = 6       # light 0-6h before CBTmin delays the clock, 0-6h after advances it
CAFFEINE_GAP = 8       # hours from last caffeine to sleep (half-life ~5h)
MAX_DAYS = 10          # stop the daily plan here even if residual shift remains
DONE_BELOW = 1.0       # residual shift (h) treated as adjusted
SLEEP_AFTER_TAKEOFF_H = 0.5    # Paul can't fall asleep until 30 minutes after takeoff
WAKE_BEFORE_LANDING_H = 0.75   # and must be up 45 minutes before landing at the latest
LAYOVER_SLEEP_MIN_H = 6        # shorter layovers: stay awake in the terminal
LAYOVER_PAD_H = (0.5, 1.5)     # layover sleep starts 30 min after landing, ends 90 min before departure
MIN_SLEEP_H = 1.0              # shorter overlaps with destination night are not worth a Sleep block
MIN_EVENT_H = 0.5              # no calendar block shorter than this
BODY_NIGHT = (23.0, 6.0)       # body clock hours counted as "awake through body night"
SLEEP_TITLE = "Jet Lag - Sleep \U0001F634"
AWAKE_TITLE = "Jet Lag - Awake ☀️"
UTC = timezone.utc


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def hm(s):
    h, m = s.split(":")
    return int(h) + int(m) / 60


def wrap(h):
    """Map hours onto (-12, 12]."""
    h = (h + 12) % 24 - 12
    return 12.0 if h == -12 else h


def local(dt_str, tz):
    """Parse a local wall time into an absolute UTC instant, so all later arithmetic is exact."""
    try:
        return datetime.fromisoformat(dt_str).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)
    except Exception as e:  # bad zone or bad timestamp
        die(f"{dt_str} / {tz}: {e}")


def fmt(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%a %b %d %H:%M")


def wall(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def clock(x):
    x %= 24
    return f"{int(x):02d}:{int(x % 1 * 60):02d}"


def main():
    if len(sys.argv) != 2:
        die("usage: jetlag_plan.py trip.json")
    trip = json.load(open(sys.argv[1]))
    dest, body = trip["dest_tz"], trip["body_tz"]
    zb, zd = ZoneInfo(body), ZoneInfo(dest)
    wake, bed = hm(trip.get("wake", "06:30")), hm(trip.get("bed", "22:30"))
    legs = trip["legs"]
    if not legs:
        die("no legs")
    dep0 = local(legs[0]["dep"], legs[0]["dep_tz"])
    arr = local(legs[-1]["arr"], legs[-1]["arr_tz"])
    if arr <= dep0:
        die("trip arrives before it departs")

    off_body = dep0.astimezone(zb).utcoffset().total_seconds() / 3600
    off_dest = arr.astimezone(zd).utcoffset().total_seconds() / 3600
    s = wrap(off_dest - off_body)  # + means destination clock is ahead
    if 0 < s <= MAX_ADVANCE:
        mode, need, sign, rate = "advance", s, -1, ADV_RATE
    else:
        mode, need, sign, rate = "delay", (24 - s) % 24 if s > 0 else -s, 1, DEL_RATE
    if need < 2:
        mode = "none"

    # CBTmin as a UTC clock hour; it moves `sign * rate` h per day from takeoff.
    cbt_body_wall = (wake - CBT_BEFORE_WAKE) % 24
    phi0 = (cbt_body_wall - off_body) % 24

    def shifted(t):
        days = max(0.0, (t - dep0).total_seconds() / 86400)
        return 0.0 if mode == "none" else min(need, days * rate)

    def phi(t):
        return (phi0 + sign * shifted(t)) % 24

    def rel(t):
        """Hours from CBTmin: negative = before it, positive = after it."""
        u = t.astimezone(UTC)
        return wrap(u.hour + u.minute / 60 - phi(t))

    def light(t):
        h = rel(t)
        if -LIGHT_WINDOW <= h < 0:
            effect = "delay"
        elif 0 <= h < LIGHT_WINDOW:
            effect = "advance"
        else:
            return "neutral"
        if mode == "none":
            return "neutral"
        return "seek" if effect == mode else "avoid"

    def body_hour(t):
        """Hour of day it feels like: body_tz clock, corrected for the shift so far."""
        return round((cbt_body_wall + rel(t)) % 24 * 4) / 4 % 24

    def dest_night(t):
        h = t.astimezone(zd)
        x = h.hour + h.minute / 60
        return x >= bed or x < wake if bed > wake else bed <= x < wake

    def melatonin(t):
        h = rel(t)
        if mode == "delay" and 0 <= h <= 10:
            return "yes"
        if mode == "advance" and -12 < h <= -5:
            return "yes"
        return "no"

    def runs(start, end, key):
        """Split [start, end) into contiguous runs of key(t), sampled every 15 min."""
        out, t, cur, s0 = [], start, None, start
        while t < end:
            k = key(t)
            if k != cur:
                if cur is not None:
                    out.append((s0, t, cur))
                cur, s0 = k, t
            t += timedelta(minutes=15)
        out.append((s0, end, cur))
        return out

    def body_night_hours(a, b):
        n, t = 0, a
        while t < b:
            h = body_hour(t)
            n += h >= BODY_NIGHT[0] or h < BODY_NIGHT[1]
            t += timedelta(minutes=15)
        return n * 0.25

    events = []

    def add_event(kind, a, b, zone, context):
        if (b - a).total_seconds() / 3600 < MIN_EVENT_H:
            return
        ev = {"kind": kind, "title": SLEEP_TITLE if kind == "sleep" else AWAKE_TITLE,
              "context": context, "zone": zone,
              "start": wall(a, zone), "end": wall(b, zone),
              "start_utc": a.isoformat(), "end_utc": b.isoformat(),
              "body_from": clock(body_hour(a)), "body_to": clock(body_hour(b))}
        if kind == "sleep":
            ev["sleep_hours"] = round((b - a).total_seconds() / 3600, 1)
            ev["caffeine_cutoff"] = fmt(a - timedelta(hours=CAFFEINE_GAP), zone)
            ev["melatonin"] = melatonin(a)
        else:
            ev["light"] = [{"from": fmt(x, zone), "to": fmt(y, zone), "light": li}
                           for x, y, li in runs(a, b, light) if li != "neutral"]
            ev["body_night_awake_h"] = body_night_hours(a, b)
        events.append(ev)

    def add_merged(segs, zone, context):
        """One calendar block per contiguous sleep or awake stretch, whatever the light does inside."""
        cur = None
        for a, b, sl in segs:
            if cur and cur[2] == sl:
                cur = (cur[0], b, sl)
            else:
                if cur:
                    add_event("sleep" if cur[2] else "awake", cur[0], cur[1], zone, context)
                cur = (a, b, sl)
        if cur:
            add_event("sleep" if cur[2] else "awake", cur[0], cur[1], zone, context)

    sleeps = []  # in-flight sleep starts, for the caffeine cutoff

    def window(start, end, tz, bounds, context):
        """Sleep happens only where destination night overlaps `bounds` (None = never)."""
        grid, t = [], start
        while t < end:
            grid.append(t)
            t += timedelta(minutes=15)
        mask = {g: bool(bounds) and bounds[0] <= g < bounds[1] and dest_night(g) for g in grid}
        i = 0
        while i < len(grid):  # drop sleep runs too short to be worth a block
            if mask[grid[i]]:
                j = i
                while j < len(grid) and mask[grid[j]]:
                    j += 1
                if (j - i) * 0.25 < MIN_SLEEP_H:
                    for g in grid[i:j]:
                        mask[g] = False
                i = j
            else:
                i += 1
        segs, sleep_runs = [], []
        for a, b, (sl, li) in runs(start, end, lambda t: (mask[t], light(t))):
            if sl and (not segs or segs[-1]["sleep"] != "sleep"):
                sleeps.append((a, tz))
            segs.append({"dest_from": fmt(a, dest), "dest_to": fmt(b, dest),
                         "local_from": fmt(a, tz), "local_to": fmt(b, tz),
                         "body_from": clock(body_hour(a)), "body_to": clock(body_hour(b)),
                         "sleep": "sleep" if sl else "awake", "light": li,
                         "melatonin_if_sleep_starts_here": melatonin(a) if sl else None})
            sleep_runs.append((a, b, sl))
        # The 15-minute grid can overshoot the bounds by up to 14 minutes: clip sleep to them
        # and let the neighbouring awake runs absorb the difference.
        for n, (a, b, sl) in enumerate(sleep_runs):
            if sl:
                ca, cb = max(a, bounds[0]), min(b, bounds[1])
                sleep_runs[n] = (ca, cb, sl)
                if n and not sleep_runs[n - 1][2]:
                    sleep_runs[n - 1] = (sleep_runs[n - 1][0], ca, False)
                if n + 1 < len(sleep_runs) and not sleep_runs[n + 1][2]:
                    sleep_runs[n + 1] = (cb, sleep_runs[n + 1][1], False)
        add_merged(sleep_runs, tz, context)
        return segs

    timeline = []
    prev = None
    for n, leg in enumerate(legs, 1):
        d, a = local(leg["dep"], leg["dep_tz"]), local(leg["arr"], leg["arr_tz"])
        if a <= d:
            die(f"leg {leg['from']}-{leg['to']} arrives before it departs")
        if prev is not None:
            gap = (d - prev[0]).total_seconds() / 3600
            bounds = None
            if gap >= LAYOVER_SLEEP_MIN_H:
                bounds = (prev[0] + timedelta(hours=LAYOVER_PAD_H[0]), d - timedelta(hours=LAYOVER_PAD_H[1]))
            timeline.append({"segment": f"layover {leg['from']}", "hours": round(gap, 1),
                             "windows": window(prev[0], d, prev[1], bounds, f"layover {leg['from']}")})
        bounds = (d + timedelta(hours=SLEEP_AFTER_TAKEOFF_H), a - timedelta(hours=WAKE_BEFORE_LANDING_H))
        timeline.append({"segment": f"flight {leg['from']}-{leg['to']}",
                         "windows": window(d, a, leg["dep_tz"], bounds, f"flight {leg['from']}-{leg['to']}")})
        prev = (a, leg["arr_tz"])

    days = []
    day = arr.astimezone(zd).date()
    for i in range(MAX_DAYS):
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=zd)
        left = round(need - shifted(noon), 1) if mode != "none" else 0
        cbt_dest = (phi(noon) + noon.utcoffset().total_seconds() / 3600) % 24
        awake_hours = [(wake + k / 4) % 24 for k in range(int(((bed - wake) % 24) * 4))]
        midnight = datetime(day.year, day.month, day.day, tzinfo=zd)
        wake_t = (midnight + timedelta(hours=wake)).astimezone(UTC)
        bed_t = (midnight + timedelta(hours=bed)).astimezone(UTC)
        next_wake = (midnight + timedelta(days=1, hours=wake)).astimezone(UTC)
        start = max(arr, wake_t)
        lowwin = f"{clock(cbt_dest - 1.5)}-{clock(cbt_dest + 1.5)}"
        days.append({
            "date": day.isoformat(),
            "residual_shift_h": left,
            "cbtmin_dest": clock(cbt_dest),
            "low_point_in_waking_hours": any(abs(wrap(x - cbt_dest)) <= 1.5 for x in awake_hours),
            "low_window_dest": lowwin,
            "light_windows_waking": [{"from": fmt(a, dest), "to": fmt(b, dest), "light": li}
                                     for a, b, li in runs(start, bed_t, light) if li != "neutral"],
            "caffeine_cutoff": clock(bed - CAFFEINE_GAP),
            "melatonin_at_bed": melatonin(bed_t),
        })
        if left < DONE_BELOW:
            break
        day += timedelta(days=1)

    events.sort(key=lambda e: e["start_utc"])
    first_ctx = f"flight {legs[0]['from']}-{legs[0]['to']}"
    first_flight_awake_h = sum(e["body_night_awake_h"] for e in events
                               if e["kind"] == "awake" and e["context"] == first_ctx)
    flight_sleep_h = sum(e["sleep_hours"] for e in events if e["kind"] == "sleep" and e["context"].startswith(("flight", "layover")))
    landing_body = body_hour(arr)
    warnings = []
    if mode != "none" and not any(e["kind"] == "sleep" and e["context"].startswith("flight") for e in events):
        warnings.append("No in-flight sleep fits between takeoff+30min, landing-45min and destination night: stay awake and land on the destination day.")
    elif flight_sleep_h < 4 and mode != "none":
        warnings.append(f"Only {flight_sleep_h:.1f}h of in-flight sleep is possible.")
    if landing_body >= BODY_NIGHT[0] or landing_body < BODY_NIGHT[1]:
        warnings.append(f"Body clock reads {clock(landing_body)} at landing: expect to be groggy; plan the arrival day around it.")

    print(json.dumps({
        "shift_h": s, "mode": mode, "need_h": need,
        "rate_h_per_day": rate if mode != "none" else 0,
        "est_days": 0 if mode == "none" else round(need / rate, 1),
        "residual_shift_at_landing_h": round(max(0.0, need - shifted(arr)), 1) if mode != "none" else 0,
        "body_clock_at_landing": clock(landing_body),
        "body_cbtmin_now": f"{clock(cbt_body_wall)} {body}",
        "departure_local": fmt(dep0, legs[0]["dep_tz"]),
        "first_flight_body_night_awake_h": first_flight_awake_h,
        "warnings": warnings,
        "flight_sleep": [{"starts_dest": fmt(a, dest), "starts_local": fmt(a, tz),
                          "caffeine_cutoff_dest": fmt(a - timedelta(hours=CAFFEINE_GAP), dest),
                          "caffeine_cutoff_local": fmt(a - timedelta(hours=CAFFEINE_GAP), tz)}
                         for a, tz in sleeps],
        "events": events, "timeline": timeline, "days": days}, indent=1))


if __name__ == "__main__":
    main()
