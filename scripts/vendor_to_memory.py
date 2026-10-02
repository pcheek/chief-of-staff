#!/usr/bin/env python3
"""Copy the calendar-manager plugin into the memory repo's .claude/ for cloud routines.

Cloud sessions don't install plugins, not even ones a repo enables in .claude/settings.json
(code.claude.com/docs/en/cloud-environments, "What carries over from your setup"). A
session started on a single repository does load that repo's .claude/skills, .claude/agents
and .claude/settings.json hooks. So the memory repo carries a generated copy:

    .claude/calendar-manager/   the plugin (scripts, skills, agents, references), with
                                ${CLAUDE_PLUGIN_ROOT} pointed at this folder
    .claude/skills/calendar-*/  the plugin's skills as project skills, renamed because
                                project skills have no plugin namespace:
                                /calendar-manager:run -> /calendar-run, and so on
    .claude/agents/*.md         the plugin's agents
    .claude/settings.json       the guard hook, from hooks/hooks.json (other keys kept)
    .claude/calendar-manager/VENDORED.json   version and source commit

chief-of-staff stays the source of truth: never edit the copy, re-run this instead.

    python3 scripts/vendor_to_memory.py /path/to/calendar-manager-memory
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "calendar-manager")
PLUGIN_ROOT_IN_SHELL = "${CLAUDE_PROJECT_DIR:-.}/.claude/calendar-manager"
PLUGIN_ROOT_IN_HOOKS = "$CLAUDE_PROJECT_DIR/.claude/calendar-manager"
SKILL_NAMES = {
    "run": "calendar-run",
    "guidance": "calendar-guidance",
    "promote-guidance": "calendar-promote-guidance",
    "schedule": "calendar-schedule",
    "calendar-sop": "calendar-sop",
}
COPY_DIRS = ("scripts", "skills", "agents", ".claude-plugin")
TEXT_EXT = (".md", ".json", ".py")


def rewrite(text):
    text = text.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT_IN_SHELL)
    for old, new in SKILL_NAMES.items():
        text = text.replace("/calendar-manager:%s" % old, "/" + new)
        text = text.replace("calendar-manager:%s" % old, new)
    return text.replace("/calendar-manager:*", "/calendar-*")


def rename_skill(text, new_name):
    return re.sub(r"^name: .*$", "name: %s" % new_name, text, count=1, flags=re.M)


def copy_tree(src, dst, transform=None):
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        rel = os.path.relpath(dirpath, src)
        out_dir = os.path.normpath(os.path.join(dst, rel))
        os.makedirs(out_dir, exist_ok=True)
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            s, d = os.path.join(dirpath, name), os.path.join(out_dir, name)
            if name.endswith(TEXT_EXT) and transform:
                with open(s, encoding="utf-8") as fh:
                    body = transform(fh.read(), os.path.relpath(s, src))
                with open(d, "w", encoding="utf-8") as fh:
                    fh.write(body)
            else:
                shutil.copy2(s, d)


def source_commit():
    res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "calendar-manager"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    return (res.stdout.strip() or "unknown") + ("-dirty" if dirty else "")


def vendor(memory):
    memory = os.path.realpath(memory)
    claude = os.path.join(memory, ".claude")
    target = os.path.join(claude, "calendar-manager")
    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        version = json.load(fh)["version"]

    # 1. The plugin copy.
    if os.path.isdir(target):
        shutil.rmtree(target)
    for d in COPY_DIRS:
        copy_tree(os.path.join(PLUGIN, d), os.path.join(target, d),
                  lambda body, rel: rewrite(body))

    # 2. Project skills.
    skills_dir = os.path.join(claude, "skills")
    for old, new in SKILL_NAMES.items():
        out = os.path.join(skills_dir, new)
        if os.path.isdir(out):
            shutil.rmtree(out)
        copy_tree(os.path.join(PLUGIN, "skills", old), out,
                  lambda body, rel, new=new: rename_skill(rewrite(body), new)
                  if rel == "SKILL.md" else rewrite(body))

    # 3. Agents.
    agents_dir = os.path.join(claude, "agents")
    os.makedirs(agents_dir, exist_ok=True)
    agent_files = sorted(f for f in os.listdir(os.path.join(PLUGIN, "agents")) if f.endswith(".md"))
    for name in agent_files:
        with open(os.path.join(PLUGIN, "agents", name), encoding="utf-8") as fh:
            body = rewrite(fh.read())
        with open(os.path.join(agents_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    # 4. Hooks into .claude/settings.json, keeping any other keys.
    with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as fh:
        hooks = json.loads(fh.read().replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT_IN_HOOKS))
    settings_path = os.path.join(claude, "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as fh:
            settings = json.load(fh)
    except (OSError, ValueError):
        settings = {}
    settings["hooks"] = hooks["hooks"]
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")

    # 5. Stamp.
    stamp = {
        "plugin": "calendar-manager",
        "version": version,
        "source": "pcheek/chief-of-staff@%s" % source_commit(),
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "skills": ["/" + n for n in SKILL_NAMES.values()],
        "agents": [f[:-3] for f in agent_files],
        "note": "Generated by scripts/vendor_to_memory.py. Do not edit; re-vendor instead.",
    }
    with open(os.path.join(target, "VENDORED.json"), "w", encoding="utf-8") as fh:
        json.dump(stamp, fh, indent=2)
        fh.write("\n")
    return stamp


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("memory", help="path to a clone of pcheek/calendar-manager-memory")
    args = ap.parse_args()
    if not os.path.isfile(os.path.join(args.memory, ".calendar-manager-memory")):
        sys.exit("%s has no .calendar-manager-memory marker; is it the memory repo?"
                 % args.memory)
    stamp = vendor(args.memory)
    print("vendored calendar-manager %s from %s" % (stamp["version"], stamp["source"]))


if __name__ == "__main__":
    main()
