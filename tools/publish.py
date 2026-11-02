#!/usr/bin/env python3
"""Publishes the recipe repository (store build order, step 4): checks everything, writes the index, signs it.
The same file serves the maintainer (with a private word list and the expected key next to it) and anyone who forks
the public repository (tools/publish.py there: bring your own key and, if you like, your own word list).

    publish.py <recipe-repo-folder> --key <private signing key> [--days 30]
    publish.py <recipe-repo-folder> --check-only                      (no key needed: checks only, writes nothing)
    options: --private-words FILE   words that must never be published (default: private-words.txt next to this file,
                                    if it exists — keep it OUT of the public repository: it lists what it looks for)
             --expect-key FILE.pub  refuse to sign with any other key (default: <repository id>-signing.pub next to
                                    this file, if it exists); --new-key for a deliberate key change

1. repository.yaml: schema 1, a plain id, name, maintainer, url.
2. Every <app>/recipe.yaml passes the updater's own checker, and its id is <repository id>.<app>.
3. No home details anywhere (the word list, every file's text and name) and nothing that looks like a secret.
4. Only the files the standard allows (repository.yaml, README.md, LICENSE, STANDARD.md, TEMPLATE.yaml, .gitignore,
   index.yaml(.sig), <app>/recipe.yaml, <app>/description.md, <app>/icon.png|webp, <app>/screenshots/*.png|webp,
   examples/<app>/recipe.yaml — checked, never indexed — and tools/*.py, tools/lib/homelab_updater/*.py).
5. index.yaml: each recipe's path, SHA-256 and size; serial = the time (always higher than the last); expires.
6. Signs it with `ssh-keygen -Y sign` (it asks the key's passphrase itself), then checks the result exactly as the
   updater will, with the key's .pub. Nothing is pushed: the git commands are printed, to run by hand.
"""

import argparse, datetime as dt, hashlib, re, subprocess, sys
sys.dont_write_bytecode = True          # no __pycache__ in the repository folder (publish refuses stray files)
from pathlib import Path

HERE = Path(__file__).resolve().parent
for lib in (HERE / "lib", HERE.parent / "updater"):          # the public tools/lib, or the private homelab repository
    if (lib / "homelab_updater" / "recipe_check.py").is_file():
        sys.path.insert(0, str(lib)); break
from homelab_updater import recipe_check as rc, repo_index as ri       # noqa: E402

TOP_FILES = {"repository.yaml", "README.md", "LICENSE", "STANDARD.md", "TEMPLATE.yaml", ".gitignore", "index.yaml", "index.yaml.sig"}
APP_FILE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}/(recipe\.yaml|description\.md|icon\.(png|webp)|screenshots/[a-z0-9_-]{1,40}\.(png|webp))$")
OTHER_FILE = re.compile(r"^(examples/[a-z0-9][a-z0-9-]{0,59}/recipe\.yaml|tools/[a-z0-9_-]{1,40}\.py|tools/lib/homelab_updater/[a-z0-9_]{1,40}\.py)$")
# what tokens look like — written in pieces, so this file never contains them whole (it's published itself)
SECRETS = re.compile("|".join(["tsk" "ey-", "gh" "p_", "github" "_pat_", "glp" "at-", "xox" "[bap]-", "sk" "-[A-Za-z0-9]{20}",
                               "-----BEGIN [A-Z ]*PRIV" "ATE KEY", "AK" "IA[0-9A-Z]{16}"]))


def problems(repo, words_file=None):
    """(errors, notes, repository id, {app: bytes})."""
    err, notes, recipes = [], [], {}
    try:
        meta = rc.parse((repo / "repository.yaml").read_bytes())
    except (OSError, rc.Refused) as e:
        return [f"repository.yaml: {e}"], notes, None, recipes
    rid = meta.get("id")
    if meta.get("schema") != 1 or not isinstance(rid, str) or not ri.REPO_ID.match(rid):
        return ["repository.yaml: schema 1 and a plain lowercase id"], notes, None, recipes
    for k in ("name", "maintainer", "url"):
        if not isinstance(meta.get(k), str) or not meta[k]:
            err.append(f"repository.yaml: needs '{k}'")
    wf = Path(words_file) if words_file else HERE / "private-words.txt"
    words = [w.strip().lower() for w in wf.read_text().splitlines() if w.strip() and not w.startswith("#")] if wf.is_file() else []
    if not words:
        notes.append("no private word list: only secrets and files are checked, not your home's details")
    for f in sorted(p for p in repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(repo).parts):
        rel = f.relative_to(repo).as_posix()
        if rel not in TOP_FILES and not APP_FILE.match(rel) and not OTHER_FILE.match(rel):
            err.append(f"{rel}: not a file the repository may hold")
        if rel in ("index.yaml", "index.yaml.sig"):
            continue
        data = f.read_bytes()
        text = data.decode("utf-8", "replace").lower()
        for w in words:
            if w in text or w in rel.lower():
                err.append(f"{rel}: contains a home detail ({w!r}) — never published")
        if SECRETS.search(data.decode("utf-8", "replace")):
            err.append(f"{rel}: contains something that looks like a secret — never published")
    for f in sorted((repo / "examples").glob("*/recipe.yaml")):         # examples: must pass, never indexed
        try:
            e, _ = rc.check(rc.parse(f.read_bytes()), "example")
        except rc.Refused as x:
            e = [str(x)]
        err += [f"examples/{f.parent.name}: {x}" for x in e]
    for d in sorted(p for p in repo.iterdir() if p.is_dir() and p.name not in (".git", "examples", "tools")):
        f = d / "recipe.yaml"
        if not f.is_file():
            continue
        data = f.read_bytes()
        try:
            r = rc.parse(data)
        except rc.Refused as e:
            err.append(f"{d.name}: {e}"); continue
        if r.get("id") != f"{rid}.{d.name}":
            err.append(f"{d.name}: its id must be {rid}.{d.name}")
        e, w = rc.check(r, rid)
        err += [f"{d.name}: {x}" for x in e]
        notes += [f"{d.name}: {x}" for x in w]
        recipes[d.name] = data
    return err, notes, rid, recipes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo"); ap.add_argument("--key"); ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--new-key", action="store_true", help="sign with a key other than the expected one (a key change)")
    ap.add_argument("--private-words"); ap.add_argument("--expect-key")
    a = ap.parse_args()
    repo = Path(a.repo)
    err, notes, rid, recipes = problems(repo, a.private_words)
    for n in notes:
        print("note:", n)
    if err:
        sys.exit("NOT PUBLISHED:\n  " + "\n  ".join(err))
    print(f"checked: repository {rid}, {len(recipes)} recipe(s): {', '.join(recipes) or 'none'}; no home details found")
    if a.check_only:
        return
    if not a.key or not 1 <= a.days <= 90:
        sys.exit("--key <private key> is needed, and --days must be 1–90")
    key = Path(a.key)
    pub = Path(str(key) + ".pub").read_text()
    expected = Path(a.expect_key) if a.expect_key else HERE / f"{rid}-signing.pub"   # the key updaters pinned
    if expected.is_file() and ri.pinned_key(expected.read_text()) != ri.pinned_key(pub) and not a.new_key:
        sys.exit(f"this isn't the repository's signing key ({ri.fingerprint(expected.read_text())}); "
                 f"every updater that pinned it would refuse the index. (A deliberate key change: --new-key)")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    serial = int(now.strftime("%Y%m%d%H%M%S"))
    old = repo / "index.yaml"
    if old.is_file():
        m = re.search(r"(?m)^serial: (\d+)$", old.read_text())
        if m and int(m.group(1)) >= serial:
            sys.exit("the existing index has a higher serial: is this machine's clock right?")
    lines = ["# Made by publish.py — do not edit by hand: the signature (index.yaml.sig) covers every byte.",
             "schema: 1", f"repository: {rid}", f"serial: {serial}",
             f"generated: '{now:%Y-%m-%dT%H:%M:%SZ}'", f"expires: '{now + dt.timedelta(days=a.days):%Y-%m-%dT%H:%M:%SZ}'",
             "recipes:" if recipes else "recipes: {}"]
    for app, data in sorted(recipes.items()):
        lines.append(f"  {app}: {{path: {app}/recipe.yaml, sha256: {hashlib.sha256(data).hexdigest()}, size: {len(data)}}}")
    index = ("\n".join(lines) + "\n").encode()
    old.write_bytes(index)
    sig = repo / "index.yaml.sig"
    sig.unlink(missing_ok=True)
    r = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", ri.NAMESPACE, str(old)])
    if r.returncode != 0 or not sig.is_file():
        sys.exit("signing failed: nothing to push (index.yaml is written but unsigned — run again)")
    ix = ri.verify_index(index, sig.read_bytes(), {"id": rid, "key": pub, "last_serial": 0})       # as the updater will
    for app, data in recipes.items():
        ri.verify_recipe(ix, app, data)
    print(f"signed and checked as the updater will: serial {serial}, expires {now + dt.timedelta(days=a.days):%d %b %Y}")
    print(f"key {ri.fingerprint(pub)}")
    print(f"\nthen, in {repo}:\n  git add -A && git commit -m 'Publish {serial}' && git push")


if __name__ == "__main__":
    main()
