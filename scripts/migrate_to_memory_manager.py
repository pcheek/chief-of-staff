#!/usr/bin/env python3
"""Finish the memory-manager move in a clone of the memory repo. Paul runs this, once, in his own terminal.

The calendar-manager guard blocks every agent session from editing the marker, .gitattributes and
.claude/ in the memory repo, on purpose, so an agent cannot loosen its own guard. The PR on the memory
repo moves the data (calendar/, email/, shared/). This script does the three guarded parts:

    1. replace the .calendar-manager-memory marker with .memory-manager
    2. point .gitattributes at calendar/guidance.json and friends
    3. re-vendor the plugin into .claude/ from this checkout

    python3 scripts/migrate_to_memory_manager.py /path/to/clone [--dry-run]

It refuses to run on a dirty tree or on a clone that has not had the data moved. It commits nothing:
review `git diff`, then commit and push yourself.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NEW_MARKER = (
    "This file marks this repository as Paul's memory-manager. The calendar-manager guard treats every\n"
    "Claude session inside this folder as a calendar-manager run, and guidance.py finds its data in calendar/.\n"
    "Email runs must not start here: start them in the marketplace checkout and reach this repo by path.\n"
)
ATTRIBUTES = ("# guidance.py sync registers these drivers in each clone's git config.\n"
              "calendar/guidance.json merge=calendar-guidance\n"
              "calendar/guidance.md merge=calendar-render\n"
              "calendar/questions.md merge=calendar-render\n")


def run(clone, *args):
    return subprocess.run(["git", "-C", clone, *args], capture_output=True, text=True)


def migrate(clone, dry_run=False):
    clone = os.path.realpath(clone)
    problems = []
    if run(clone, "rev-parse", "--show-toplevel").returncode != 0:
        return ["%s is not a git clone" % clone]
    if run(clone, "status", "--porcelain").stdout.strip():
        problems.append("working tree is not clean")
    if not os.path.isfile(os.path.join(clone, "calendar", "guidance.json")):
        problems.append("calendar/guidance.json is missing: merge the data-move PR first")
    if os.path.exists(os.path.join(clone, "guidance.json")):
        problems.append("guidance.json is still at the repo root: merge the data-move PR first")
    legacy = os.path.join(clone, ".calendar-manager-memory")
    new = os.path.join(clone, ".memory-manager")
    if not os.path.isfile(legacy) and not os.path.isfile(new):
        problems.append("neither marker exists; is this the memory repo?")
    if problems or dry_run:
        return problems
    if os.path.isfile(legacy):
        res = run(clone, "mv", ".calendar-manager-memory", ".memory-manager")
        if res.returncode != 0:
            return ["git mv failed: " + res.stderr.strip()]
    with open(new, "w", encoding="utf-8") as fh:
        fh.write(NEW_MARKER)
    with open(os.path.join(clone, ".gitattributes"), "w", encoding="utf-8") as fh:
        fh.write(ATTRIBUTES)
    out = subprocess.run([sys.executable, os.path.join(HERE, "vendor_to_memory.py"), clone],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return ["vendor_to_memory.py failed: " + out.stderr.strip()]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("clone")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    problems = migrate(a.clone, a.dry_run)
    if problems:
        for p in problems:
            print("STOP: " + p)
        return 1
    print("checks passed" if a.dry_run else "done. Review `git diff`, then commit and push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
