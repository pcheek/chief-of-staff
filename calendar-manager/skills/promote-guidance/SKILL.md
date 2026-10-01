---
name: promote-guidance
description: "Promotes Paul's stable calendar guidance into the calendar-manager plugin itself, via a reviewed pull request on pcheek/chief-of-staff. Takes rules from ~/.claude/calendar-manager/guidance.md that have held for at least two runs, folds them into the calendar SOP (learned.md, or the relevant reference or agent file), opens a PR for human review, and marks them promoted once it merges. Use monthly, or when Paul says promote, bake in, or make permanent his calendar rules."
---

# Promote learned calendar rules into the plugin

Local guidance takes effect immediately, but only on this machine. Promoting it puts the
rules into the plugin, where they're versioned and reviewed, and they work on any machine.
Nothing an AI wrote ships unread, so this always goes through a PR.

`G` = `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py"`

## Steps

1. `G candidates --min-runs 2`. If it returns nothing, say so and stop.
2. Find or clone `pcheek/chief-of-staff`. Work on a new branch from `main`:
   `calendar-guidance-<YYYY-MM-DD>`.
3. For each candidate, decide where it belongs:
   - A color, format or roster fact goes in the matching file in
     `calendar-manager/skills/calendar-sop/references/`. Edit that file in place, and remove
     any sentence the rule contradicts. If the rule changes a roster row, also clear the
     row's UNVERIFIED status.
   - A behavior rule for one agent goes in that agent's `agents/<name>.md`.
   - Anything else goes in `references/learned.md` as `- <rule> (from G12, <date>)`.
   - A rule that touches the guardrails is never promoted, because the guard is code. If it
     seems needed, raise it with Paul.
4. Bump `version` in `calendar-manager/.claude-plugin/plugin.json` (patch).
5. Run `python3 scripts/check_marketplace.py` and
   `python3 -m unittest discover -s calendar-manager/tests`. Both must pass.
6. Commit, push and open a PR. List each rule in the body with its ID, its source question
   and where it went.
7. After Paul merges it: `G promoted G12 G15 ...`.
   - Leave them active locally until then.
   - After merge, the local copies are harmless duplicates of the plugin rules.
