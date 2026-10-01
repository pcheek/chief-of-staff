#!/usr/bin/env python3
"""Repo-wide checks that run before a push.

Things drift silently and each one costs somebody a confusing failure:

1. A plugin.json description over 500 characters fails the install, with an error that
   names neither the limit nor the text to cut.
2. A SKILL.md frontmatter description over 1024 characters fails the same way.
3. A plugin in marketplace.json with no row in the README's Plugins table exists for
   Claude Code and is invisible to a person reading the repo.
4. Marketplace syncs read each plugin's description from marketplace.json, not
   plugin.json, and skip a plugin whose entry is over 500 characters. They also skip a
   skill whose description contains anything that looks like an XML tag (<name>).

    python3 scripts/check_marketplace.py [--fix-nothing]

Exits non-zero when anything fails. Reports every problem rather than stopping at the
first, so one run tells you everything to fix.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DESC_MAX = 500
SKILL_DESC_MAX = 1024

failures = []


def fail(msg):
    failures.append(msg)
    print("  FAIL  %s" % msg)


def ok(msg):
    print("  pass  %s" % msg)


def skill_description(path):
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    fm = re.match(r"---\n(.*?)\n---", body, re.S)
    if not fm:
        return None
    m = re.search(r"^description:\s*(.*?)(?=\n[a-z_-]+:\s|\Z)", fm.group(1), re.S | re.M)
    return m.group(1).strip() if m else None


def main():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
        market = json.load(fh)
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()

    print("\nplugin.json descriptions (limit %d)" % PLUGIN_DESC_MAX)
    for manifest in sorted(glob.glob(os.path.join(ROOT, "*", ".claude-plugin", "plugin.json"))):
        rel = os.path.relpath(manifest, ROOT)
        with open(manifest, encoding="utf-8") as fh:
            desc = json.load(fh).get("description", "")
        n = len(desc)
        if n > PLUGIN_DESC_MAX:
            fail("%s is %d, cut %d" % (rel, n, n - PLUGIN_DESC_MAX))
        else:
            ok("%s %d" % (rel, n))

    print("\nmarketplace.json descriptions (limit %d)" % PLUGIN_DESC_MAX)
    for entry in market["plugins"]:
        n = len(entry.get("description", ""))
        if n > PLUGIN_DESC_MAX:
            fail("marketplace.json entry %s is %d, cut %d" % (entry["name"], n, n - PLUGIN_DESC_MAX))
        else:
            ok("marketplace.json entry %s %d" % (entry["name"], n))

    print("\nSKILL.md descriptions (limit %d)" % SKILL_DESC_MAX)
    for skill_md in sorted(glob.glob(os.path.join(ROOT, "*", "skills", "*", "SKILL.md"))):
        rel = os.path.relpath(skill_md, ROOT)
        desc = skill_description(skill_md)
        if desc is None:
            fail("%s has no frontmatter description" % rel)
            continue
        n = len(desc)
        tag = re.search(r"<[A-Za-z/][^>]*>", desc)
        if n > SKILL_DESC_MAX:
            fail("%s is %d, cut %d" % (rel, n, n - SKILL_DESC_MAX))
        elif tag:
            fail("%s description contains an XML-like tag %s; use [name] or NAME instead" % (rel, tag.group(0)))
        else:
            ok("%s %d" % (rel, n))

    print("\nEvery plugin is listed in the README")
    listed = set(re.findall(r"^\| `([a-z0-9-]+)`", readme, re.M))
    for entry in market["plugins"]:
        name = entry["name"]
        if name in listed:
            ok(name)
        else:
            fail("%s is in marketplace.json but has no row in the README Plugins table"
                 % name)

    print("\n%s" % ("%d problem(s)." % len(failures) if failures else "All checks passed."))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
