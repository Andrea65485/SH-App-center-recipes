"""A recipe repository's signed index (store build order, step 4; update-wizard-plan.md).

The index (index.yaml) lists each recipe with its SHA-256 and size, a serial number and an expiry date; only the index
is signed (index.yaml.sig, `ssh-keygen -Y sign` with the maintainer's key, kept off the internet). The updater trusts
a repository through ONE pinned public key, compared and pinned by the owner when the repository is added — never
through GitHub: someone who took over the account still couldn't publish an index this accepts.

  verify_index(index, sig, repo)   → the index, or Refused: signature by the pinned key for this purpose (namespace),
                                     not expired, serial not lower than the last one accepted (no replayed old index)
  verify_recipe(index, app, data)  → the checked recipe, or Refused: size and SHA-256 as the index says, then the
                                     standard's own check (recipe_check), and its id is <repository>.<app>

The PC's own `ssh-keygen` does the cryptography (OpenSSH, as for the updater's SSH key); nothing here connects anywhere.
"""

import datetime as dt
import hashlib, os, re, subprocess, tempfile

import yaml

from . import recipe_check

NAMESPACE = "homelab-updater-recipe-index"     # a signature made with the same key for anything else never passes
MAX_INDEX = 256 * 1024
MAX_SIG = 4 * 1024
MAX_LIFETIME = dt.timedelta(days=90)
KEY = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/]{68}$")                   # the only key type accepted for signing
REPO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
APP = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
HEX = re.compile(r"^[0-9a-f]{64}$")
STAMP = "%Y-%m-%dT%H:%M:%SZ"
Refused = recipe_check.Refused


def pinned_key(line):
    """'ssh-ed25519 AAAA… [comment]' → 'ssh-ed25519 AAAA…' (the comment is dropped; the key is all that's pinned)."""
    parts = str(line).split()
    k = " ".join(parts[:2])
    if len(parts) < 2 or not KEY.match(k):
        raise Refused("the pinned key isn't an ssh-ed25519 public key")
    return k


def fingerprint(line, ssh_keygen="ssh-keygen"):
    """SHA256:… as ssh-keygen prints it — what the owner compares with the maintainer's, by another channel."""
    k = pinned_key(line)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "k.pub")
        with open(p, "w") as fh:
            fh.write(k + "\n")
        r = subprocess.run([ssh_keygen, "-l", "-E", "sha256", "-f", p], capture_output=True, text=True, timeout=30)
    m = re.search(r"SHA256:[A-Za-z0-9+/]{43}", r.stdout)
    if r.returncode != 0 or not m:
        raise Refused("ssh-keygen couldn't read the key")
    return m.group(0)


def _when(v, what):
    if isinstance(v, dt.datetime):          # YAML may already have read a timestamp
        v = v.strftime(STAMP)
    try:
        return dt.datetime.strptime(str(v), STAMP).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        raise Refused(f"index: '{what}' isn't a time like 2026-11-02T01:00:00Z")


def verify_index(index_bytes, sig_bytes, repo, ssh_keygen="ssh-keygen", now=None):
    """repo = {"id", "key" (pinned public key), "last_serial" (0 if none yet)}. → the index as a mapping."""
    if not isinstance(repo, dict) or not REPO_ID.match(str(repo.get("id", ""))):
        raise Refused("the repository's id isn't a plain name")
    if not isinstance(index_bytes, bytes) or not 0 < len(index_bytes) <= MAX_INDEX:
        raise Refused(f"the index is empty or larger than {MAX_INDEX // 1024} KiB")
    if not isinstance(sig_bytes, bytes) or not 0 < len(sig_bytes) <= MAX_SIG or not sig_bytes.startswith(b"-----BEGIN SSH SIGNATURE-----"):
        raise Refused("the index's signature is missing or not an SSH signature")
    key = pinned_key(repo.get("key", ""))
    with tempfile.TemporaryDirectory() as d:
        allowed, sig = os.path.join(d, "allowed_signers"), os.path.join(d, "index.yaml.sig")
        with open(allowed, "w") as fh:
            fh.write(f'{repo["id"]} namespaces="{NAMESPACE}" {key}\n')
        with open(sig, "wb") as fh:
            fh.write(sig_bytes)
        try:
            r = subprocess.run([ssh_keygen, "-Y", "verify", "-f", allowed, "-I", repo["id"], "-n", NAMESPACE, "-s", sig],
                               input=index_bytes, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            raise Refused(f"couldn't run ssh-keygen to check the signature ({type(e).__name__})")
    if r.returncode != 0 or not r.stdout.startswith(b'Good "' + NAMESPACE.encode() + b'" signature'):
        raise Refused("the index's signature doesn't match the pinned key: refused (nothing from this repository is used)")
    # signed by the right key — now the content: the same care as any input
    try:
        ix = yaml.load(index_bytes.decode("utf-8"), Loader=recipe_check._NoAliases)
    except Refused:
        raise
    except (yaml.YAMLError, UnicodeDecodeError, RecursionError, ValueError) as e:
        raise Refused(f"index: not readable ({type(e).__name__})")
    if not isinstance(ix, dict) or set(ix) - {"schema", "repository", "serial", "generated", "expires", "recipes"}:
        raise Refused("index: unknown fields")
    if ix.get("schema") != 1:
        raise Refused(f"index: schema {ix.get('schema')!r} unknown")
    if ix.get("repository") != repo["id"]:
        raise Refused(f"index: made for repository {str(ix.get('repository'))[:40]!r}, not {repo['id']!r}")
    serial = ix.get("serial")
    if not isinstance(serial, int) or isinstance(serial, bool) or not 0 < serial < 10**14:
        raise Refused("index: 'serial' must be a positive whole number")
    last = repo.get("last_serial", 0)
    if serial < last:
        raise Refused(f"index: serial {serial} is older than the one already accepted ({last}) — an old index replayed?")
    now = now or dt.datetime.now(dt.timezone.utc)
    made, ends = _when(ix.get("generated"), "generated"), _when(ix.get("expires"), "expires")
    if made > now + dt.timedelta(minutes=10):
        raise Refused("index: made in the future (is this PC's clock right?)")
    if not made < ends <= made + MAX_LIFETIME:
        raise Refused(f"index: its lifetime must be at most {MAX_LIFETIME.days} days")
    if now >= ends:
        raise Refused(f"index: expired on {ends:%d %b %Y} — the maintainer publishes it again (an old copy, or publishing stopped)")
    rec = ix.get("recipes")
    if not isinstance(rec, dict) or len(rec) > 500:
        raise Refused("index: 'recipes' must map app names to their files")
    for app, e in rec.items():
        if not isinstance(app, str) or not APP.match(app) or not isinstance(e, dict) or set(e) != {"path", "sha256", "size"} \
                or e["path"] != f"{app}/recipe.yaml" or not isinstance(e["sha256"], str) or not HEX.match(e["sha256"]) \
                or not isinstance(e["size"], int) or isinstance(e["size"], bool) or not 0 < e["size"] <= recipe_check.MAX_BYTES:
            raise Refused(f"index: the entry for {str(app)[:40]!r} isn't path / sha256 / size")
    return ix


def verify_recipe(ix, app, data):
    """One recipe file, fetched separately: exactly the bytes the signed index names, then the standard's check."""
    e = (ix.get("recipes") or {}).get(app)
    if not e:
        raise Refused(f"{str(app)[:40]!r} isn't in the signed index")
    if not isinstance(data, bytes) or len(data) != e["size"] or hashlib.sha256(data).hexdigest() != e["sha256"]:
        raise Refused(f"{app}: the file isn't the one the signed index names (size or SHA-256 differ): refused")
    r = recipe_check.parse(data)
    if r.get("id") != f"{ix['repository']}.{app}":
        raise Refused(f"{app}: its id must be {ix['repository']}.{app}")
    err, _ = recipe_check.check(r, ix["repository"])
    if err:
        raise Refused(f"{app}: " + "; ".join(err))
    return r
