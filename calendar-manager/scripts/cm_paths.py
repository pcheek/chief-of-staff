"""Where calendar-manager keeps things. Shared by guard.py and guidance.py.

    HOME    the memory folder: guidance.json, guidance.md, questions.md, runs/
            1. $CALENDAR_MANAGER_HOME
            2. the nearest folder (from the hook's cwd, $CLAUDE_PROJECT_DIR or the current
               directory, walking up) that holds a .calendar-manager-memory marker: the
               memory repo clone in a cloud session
            3. ~/.claude/calendar-manager (desktop fallback)
    STATE   HOME/state: guard bookkeeping. Gitignored, never committed.
    CONFIG  $CALENDAR_MANAGER_CONFIG, else HOME/config.json. Gitignored when inside HOME.
            The cloud setup script writes it outside the memory repo.

The guard's config can also come straight from $CALENDAR_MANAGER_CONFIG_JSON. That value
lives in the cloud environment's settings, is re-read every time Claude Code starts, and
cannot be changed by anything a session commits or writes. When it is set it wins.
"""
import json
import os

MARKER = ".calendar-manager-memory"
DESKTOP_HOME = "~/.claude/calendar-manager"


def _real(path):
    return os.path.realpath(os.path.expanduser(path))


def find_marker(start):
    if not start:
        return None
    d = _real(start)
    if os.path.isfile(d):
        d = os.path.dirname(d)
    while True:
        if os.path.isfile(os.path.join(d, MARKER)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def resolve_home(cwd=None):
    env = os.environ.get("CALENDAR_MANAGER_HOME")
    if env and os.path.isdir(_real(env)):
        return _real(env)
    # The variable may name the wrong clone path; the marker never does.
    for start in (cwd, os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        found = find_marker(start)
        if found:
            return found
    return _real(env or DESKTOP_HOME)


def paths(cwd=None):
    home = resolve_home(cwd)
    config = os.environ.get("CALENDAR_MANAGER_CONFIG")
    return {
        "home": home,
        "state": os.path.join(home, "state"),
        "config": _real(config) if config else os.path.join(home, "config.json"),
        "home_config": os.path.join(home, "config.json"),
    }


def load_config(config_path, defaults):
    """defaults <- config file <- $CALENDAR_MANAGER_CONFIG_JSON (highest)."""
    cfg = dict(defaults)
    try:
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update(data)
    except (OSError, ValueError):
        pass
    inline = os.environ.get("CALENDAR_MANAGER_CONFIG_JSON")
    if inline:
        try:
            data = json.loads(inline)
            if isinstance(data, dict):
                cfg.update(data)
        except ValueError:
            pass
    return cfg
