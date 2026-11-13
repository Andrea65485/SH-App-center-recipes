#!/usr/bin/env python3
"""Checks recipes against the format (STANDARD.md) with the updater's own checker, and fills one in as a test.

    python3 tools/check.py <repository folder>                    every <app>/recipe.yaml and examples/<app>/recipe.yaml
    python3 tools/check.py <recipe.yaml> --permissions            what the app would get, worked out from the recipe
    python3 tools/check.py <recipe.yaml> --fill answers.yaml      fill it in: the compose file, the .env (masked), the tips
Also prints how a Store lists it (format 2: category, licence, internet level, a key of yours; format 3: update rules
only, for an app installed by hand — never on an install page).
Needs Python 3.11+ and PyYAML."""
import sys
sys.dont_write_bytecode = True          # no __pycache__ in the repository folder (publish refuses stray files)
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from homelab_updater import recipe_check as rc          # noqa: E402


def load(path):
    try:
        return rc.parse(Path(path).read_bytes())
    except (OSError, rc.Refused) as e:
        sys.exit(f"refused: {e}")


def store_line(r):
    """How a Store lists it (format 2's facts, worked out by the same code every reader uses)."""
    if rc.update_only(r):
        return ("format 3: update rules only, for an app installed by hand (never on an install page); it matches "
                + ", ".join(r["match"]["images"]) + " — used only after the owner confirms it in the updater")
    f = rc.facts(r)
    if r["schema"] not in rc.F2:
        return "format 1: a Store lists it under Other, without licence or internet level (schema: 2 adds them)"
    if r["schema"] == rc.TOOLS_SCHEMA:          # card 60: today's updaters (0.10.2) and store-watch 1.3 leave it out
        return (f"format 4: {f['tools']} Tools-tab tile(s)" + (", reads all data you choose" if f["reads_all_data"] else "")
                + " · needs updater 0.11 + gate 1.12 + store-watch 1.4 (older readers leave this app out; the rest of "
                "the Store is unchanged)")
    key = {"needed": "needed", "optional": "only for some answers: a feature you switch on, or one of the choices", "no": "not needed"}[f["own_key"]]
    return (f"format 2: {', '.join(rc.CATEGORIES[c] for c in f['categories'])} · licence {f['licence']} ("
            + ("open source" if f["open_source"] else "not an open-source licence") + f") · internet {f['internet']} · "
            f"a key of yours {key} · " + ("runs on arm64" if f["pi"] else "not on arm64"))


def check_file(f, repo_id):
    try:
        return rc.check(rc.parse(f.read_bytes()), repo_id)
    except rc.Refused as x:
        return [str(x)], []


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1])
    if target.is_dir():
        repo = load(target / "repository.yaml")
        bad = 0
        found = [(f, repo.get("id"), f.parent.name) for f in sorted(target.glob("*/recipe.yaml"))] + \
                [(f, "example", "examples/" + f.parent.name) for f in sorted(target.glob("examples/*/recipe.yaml"))]
        for f, rid, label in found:
            e, w = check_file(f, rid)
            print(("✗ " if e else "✓ ") + label + "".join(f"\n    error: {x}" for x in e) + "".join(f"\n    note: {x}" for x in w))
            bad += bool(e)
        sys.exit(1 if bad else 0)
    r = load(target)
    e, w = rc.check(r)
    for x in w:
        print("note:", x)
    if e:
        sys.exit("refused:\n  " + "\n  ".join(e))
    print("✓ passes")
    print("  Store:", store_line(r))
    if rc.update_only(r) and ("--permissions" in sys.argv or "--fill" in sys.argv):
        sys.exit("refused: a format-3 recipe installs nothing: no permissions to show, nothing to fill in")
    try:
        if "--permissions" in sys.argv:
            for kind, what, when in rc.permissions(r):
                print(f"  {kind:9} {what}" + ("" if when == "always" else f"   [only if '{when}' is on]"))
        if "--fill" in sys.argv:
            out, env, tips, steps = rc.fill(r, load(sys.argv[sys.argv.index("--fill") + 1]))
            print(out); print("# .env —", ", ".join(f"{k}=••••" for k in env) or "nothing")
            for t in tips:
                print("# tip:", t)
            for s in steps:
                print("# by hand, on the machine:", s)
    except rc.Refused as x:
        sys.exit(f"refused: {x}")
