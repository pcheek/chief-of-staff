# chief-of-staff

Paul Cheek's personal Claude Code marketplace. These are plugins for Paul's own calendar and
life admin, kept apart from the Cheek LLC team marketplace because so much of what's in them
is personal.

## Install

```
/plugin marketplace add pcheek/chief-of-staff
/plugin install calendar-manager@chief-of-staff
```

## Plugins

| Plugin | Source | What it does |
|---|---|---|
| `calendar-manager` | bundled (`./calendar-manager`) | Eight agents run Paul's calendar SOP from cloud routines on claude.ai/code (desktop scheduled tasks as the fallback): conflict and overscheduling scans, commute drive-time, fully documented travel, color coding and free/busy, notes review, 1:1 audits, a daily Gmail sweep that flags any invite he hasn't declined that's missing from his calendar, and red busy holds on every time he (or his scheduler) offers by email. What they learn lives in the private repo `pcheek/calendar-manager-memory`, which every run pulls and pushes; cloud runs load a copy of the plugin from that repo's `.claude/` (`scripts/vendor_to_memory.py`), because cloud sessions don't install plugins. All calendar writes come from riley@cheek.org (so Paul can see what the agents made), and nothing in the past is ever touched. Strictly time-zone aware: each run works out where Paul is that day (Boston by default), and every event carries an explicit UTC offset. When an agent is unsure, it asks in that task's chat, and each answer becomes a rule every later run follows. A hook blocks deletes, invites (except Callie on flights, trains, buses, long drives and all-day travel), RSVPs and outbound messages, so agents can only create solo events and recolor or re-mark free/busy on everything else. |

## Before you push

```
python3 scripts/check_marketplace.py
python3 -m unittest discover -s calendar-manager/tests
```

After a calendar-manager release, refresh the copy the cloud routines run:

```
python3 scripts/vendor_to_memory.py ../calendar-manager-memory
```

Then commit and push `.claude/` in the memory repo as `vendor calendar-manager <version>`.

| Limit | Max |
|---|---|
| `description` in `.claude-plugin/plugin.json` and `marketplace.json` | **500** characters |
| `description` in a skill's `SKILL.md` frontmatter | **1024** characters, no XML-like tags |
