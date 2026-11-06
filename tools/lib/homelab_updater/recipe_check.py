"""Install recipes (recipe-standard-draft.md, draft 0.6): check, fill in, and work out what an app would get.
Store build order, step 2 (update-wizard-plan.md). A library for the updater; nothing here writes, connects or runs
anything. The command-line front end is recipe-examples/recipe-check.py.

A recipe comes from a repository, so it is untrusted input: every function answers "refused, because …" (a list of
reasons, or Refused) and never falls over on a malformed file. In order:
  parse(text)         YAML → a mapping: at most 64 KiB, no aliases (a 1 KB file could expand to gigabytes), no tags
  shape(r)            every field has the type, the keys and the size the standard allows
  check(r, repo_id)   the meaning: gaps declared and used rightly, only allowed compose keys, extra access declared…
  fill(r, answers)    the compose file as DATA (each value put in its place, written by the YAML library) + the .env
  permissions(r)      what the app would get, worked out from the recipe itself — never from text its author wrote
"""

import ipaddress, re, secrets, string

import yaml

MAX_BYTES = 64 * 1024
TYPES = {"folder": {"app-folder", "yours"}, "port": {"free-port"}, "secret": set(), "timezone": {"host"}, "user": {"host"},
         "choice": set(), "toggle": set(), "number": set(), "text": set(), "url": {"your-domain", "lan-address"},
         "networks": {"home-network"}}
SERVICE_KEYS = {"image", "ports", "volumes", "environment", "depends_on", "deploy", "restart", "healthcheck", "command", "user"}
USER_FORM = re.compile(r"^\{\{\s*([a-z_][a-z0-9_]*)\.uid\s*\}\}:\{\{\s*\1\.gid\s*\}\}$")   # user: "{{owner.uid}}:{{owner.gid}}" only
# Extra access a recipe may ask for, only by declaring it (needs.elevated) with a reason in plain words — and nothing else.
ELEVATED = {"host-network": ("network_mode", "host"), "net-admin": ("cap_add", "NET_ADMIN"),
            "net-raw": ("cap_add", "NET_RAW"), "tun-device": ("devices", "/dev/net/tun:/dev/net/tun")}
ELEVATED_WORDS = {"host-network": "joins the home network directly", "net-admin": "may change network settings",
                  "net-raw": "may send raw test messages", "tun-device": "a virtual network card"}
HEALTH = {"http-status", "container-health", "running-digest", "app-status", "ok-detail"}
DUMPS = {"postgres", "mariadb", "stop-and-copy", "none"}
ROLLBACK = {"image", "none"}          # after a major has started: back to the old image, or Roll back off
JARGON = re.compile(r"\b(port|volume|uid|gid|container|env|compose|ocr|cidr|subnet|daemon|mount)\b", re.I)
SLOT = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)(?:\.([a-z]+))?\s*\}\}")
WHOLE = re.compile(r"^\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}$")
UNSAFE = re.compile(r"[\n\r{}$`]")
SLOT_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}\.[a-z0-9][a-z0-9-]{0,59}$")
SUB = re.compile(r"^[a-z0-9_-]{1,40}$")
YOURS_MAX = 3                         # folders you already have, read only (gate 1.8: approved on the machine, at most 3)
TOP_KEYS = {"schema", "id", "name", "summary", "category", "version", "links", "needs", "slots", "tips", "host_steps",
            "compose", "update", "pictures"}
# pictures (recipe-pictures-design.md §8, owner 5 Nov): one icon, up to 4 screenshots, each with where it comes from.
# The files themselves are checked by pictures.py and listed (SHA-256, size) in the signed index.
PIC_ICON = re.compile(r"^icon\.(svg|png)$")
PIC_SHOT = re.compile(r"^screenshots/[1-4]\.(webp|png)$")
PIC_SOURCES = {"install", "project", "mockup"}     # a fresh install by the publisher · the app's own site or repository · a mockup
PIC_FROM = re.compile(r"^https://[A-Za-z0-9.-]{1,100}(/[A-Za-z0-9._~%/#?=&+-]{0,300})?$")
SLOT_KEYS = {"type", "question", "help", "suggest", "default", "advanced", "source", "length", "options", "on", "off",
             "under", "sub", "asked_if", "prefix"}
NEEDS_KEYS = {"platforms", "memory_mb", "elevated", "internet", "https"}


class Refused(ValueError):
    """A recipe or an answer that doesn't pass; the message says why, in words the window can show."""


class _NoAliases(yaml.SafeLoader):
    """safe_load, minus aliases: '*name' copies would let a tiny file expand without limit."""
    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise Refused("the file uses YAML aliases (*name): not allowed in a recipe")
        return super().compose_node(parent, index)


def parse(text):
    """The recipe's text → a mapping, or Refused."""
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            raise Refused(f"the file is larger than {MAX_BYTES // 1024} KiB")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            raise Refused("the file isn't UTF-8 text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise Refused(f"the file is larger than {MAX_BYTES // 1024} KiB")
    try:
        r = yaml.load(text, Loader=_NoAliases)
    except Refused:
        raise
    except yaml.MarkedYAMLError as e:                     # where it went wrong — never the text around it
        m = e.problem_mark
        where = f" at line {m.line + 1}, column {m.column + 1}" if m is not None else ""
        what = str(e.problem or e.context or type(e).__name__)[:100]
        raise Refused(f"not readable as YAML: {what}{where}" + (
            " (a value containing ': ' or starting with a special character needs quotes)"
            if "mapping values are not allowed" in what else ""))
    except (yaml.YAMLError, RecursionError, ValueError) as e:
        raise Refused(f"not readable as YAML ({type(e).__name__})")
    if not isinstance(r, dict):
        raise Refused("the file isn't a mapping of fields")
    return r


# ---- shape: types, keys and sizes, before anything reads a value

def _str(v, n=200):
    return isinstance(v, str) and len(v) <= n


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _strs(v, items=20, n=200):
    return isinstance(v, list) and len(v) <= items and all(_str(x, n) for x in v)


def _scalar(v, n=500):
    return _str(v, n) or isinstance(v, bool) or _int(v, -10**9, 10**9)


def _picture(p, where, file_re, caption):
    e = []
    if not isinstance(p, dict) or set(p) - {"file", "source", "from", "licence", "caption"}:
        return [f"pictures.{where}: file, source, and (for a picture from the project) from + licence" + (", caption" if caption else "")]
    if not (_str(p.get("file"), 40) and file_re.match(p["file"])):
        e.append(f"pictures.{where}: 'file' must be " + ("icon.svg or icon.png" if not caption else "screenshots/1.webp … 4.webp (or .png)"))
    src = p.get("source")
    if src not in PIC_SOURCES:
        e.append(f"pictures.{where}: 'source' is install (your own fresh install), project (its own site or repository) or mockup")
    if src == "project" and not (_str(p.get("from"), 400) and PIC_FROM.match(p["from"]) and _str(p.get("licence"), 120) and p["licence"].strip()):
        e.append(f"pictures.{where}: a picture from the project names where (from: https://…) and its licence")
    if src != "project" and ("from" in p or "licence" in p):
        e.append(f"pictures.{where}: 'from' and 'licence' are only for a picture from the project")
    if caption and not (_str(p.get("caption"), 120) and p["caption"].strip() and not UNSAFE.search(p["caption"])):
        e.append(f"pictures.{where}: a caption of at most 120 characters, plain text (it's also what screen readers say)")
    if not caption and "caption" in p:
        e.append(f"pictures.{where}: the icon has no caption")
    return e


def pictures_shape(pics):
    """Errors in a recipe's pictures section (the files themselves are checked by pictures.py)."""
    if not isinstance(pics, dict) or not pics or set(pics) - {"icon", "screenshots"}:
        return ["'pictures' holds an icon and/or screenshots"]
    e = []
    if "icon" in pics:
        e += _picture(pics["icon"], "icon", PIC_ICON, caption=False)
    shots = pics.get("screenshots", [])
    if not isinstance(shots, list) or len(shots) > 4:
        return e + ["pictures.screenshots: a list of at most 4"]
    for i, p in enumerate(shots, 1):
        e += _picture(p, f"screenshots[{i}]", PIC_SHOT, caption=True)
    files = [p.get("file") for p in shots if isinstance(p, dict)]
    if len(set(files)) != len(files):
        e.append("pictures.screenshots: each file only once")
    return e


def picture_files(r):
    """The picture files a passed recipe names, in order (icon first)."""
    pics = r.get("pictures") or {}
    return ([pics["icon"]["file"]] if "icon" in pics else []) + [p["file"] for p in pics.get("screenshots", [])]


def shape(r):
    """Errors in the recipe's shape (empty = every field has an allowed type and size)."""
    e = []
    if not isinstance(r, dict):
        return ["the file isn't a mapping of fields"]
    if r.get("schema") != 1:
        return [f"schema {r.get('schema')!r} unknown: refused"]
    for k in sorted(set(r) - TOP_KEYS, key=str):
        e.append(f"unknown field {str(k)[:40]!r}")
    for k in ("id", "name", "summary", "version"):
        if not _str(r.get(k), 300) or not r.get(k):
            e.append(f"'{k}' must be a short text")
    if _str(r.get("id")) and not ID.match(r["id"]):
        e.append("'id' must look like <repository>.<app> (lowercase letters, digits, dashes)")
    if "category" in r and not _str(r["category"], 40):
        e.append("'category' must be a short text")
    if "links" in r and not (isinstance(r["links"], dict) and len(r["links"]) <= 10
                             and all(_str(k, 30) and _str(v, 300) for k, v in r["links"].items())):
        e.append("'links' must map short names to addresses")
    n = r.get("needs", {})
    if not isinstance(n, dict) or set(n) - NEEDS_KEYS:
        e.append(f"'needs' may only hold {sorted(NEEDS_KEYS)}")
    else:
        if "platforms" in n and not _strs(n["platforms"], 10, 30):
            e.append("needs.platforms: a list of platform names")
        if "memory_mb" in n and not _int(n["memory_mb"], 1, 1 << 20):
            e.append("needs.memory_mb: a whole number of MB")
        for k in ("internet", "https"):
            if k in n and not _str(n[k], 300):
                e.append(f"needs.{k}: a note in plain words")
        if "elevated" in n and not (isinstance(n["elevated"], dict) and len(n["elevated"]) <= 4
                                    and all(_str(k, 30) and _str(v, 300) for k, v in n["elevated"].items())):
            e.append("needs.elevated: items with a reason in plain words")
    if "pictures" in r:
        e += pictures_shape(r["pictures"])
    slots = r.get("slots")
    if not isinstance(slots, dict) or len(slots) > 40:
        e.append("'slots' must map gap names to their description (at most 40)")
        slots = {}
    for name, s in slots.items():
        where = f"slot {str(name)[:40]!r}"
        if not isinstance(name, str) or not SLOT_NAME.match(name):
            e.append(f"{where}: a gap's name is lowercase letters, digits and _"); continue
        if not isinstance(s, dict):
            e.append(f"{where}: must be a mapping"); continue
        if set(s) - SLOT_KEYS:
            e.append(f"{where}: unknown keys {sorted(map(str, set(s) - SLOT_KEYS))}")
        if not _str(s.get("type"), 20):
            e.append(f"{where}: needs a 'type'")
        for k, n_ in (("question", 200), ("help", 600), ("suggest", 30), ("source", 20), ("on", 300), ("off", 300),
                      ("under", 40), ("asked_if", 40), ("prefix", 60)):
            if k in s and not _str(s[k], n_):
                e.append(f"{where}: '{k}' must be a text")
        if "sub" in s and not (_str(s["sub"]) and SUB.match(s["sub"])):
            e.append(f"{where}: 'sub' is one plain folder name")
        if "length" in s and not _int(s["length"], 0, 1000):
            e.append(f"{where}: 'length' must be a number")
        if "advanced" in s and not isinstance(s["advanced"], bool):
            e.append(f"{where}: 'advanced' is true or false")
        if "default" in s and not (_scalar(s["default"]) or _strs(s["default"], 10, 60)):
            e.append(f"{where}: 'default' must be a plain value")
        if "options" in s:
            o = s["options"]
            if not ((isinstance(o, list) and 0 < len(o) <= 50 and all(_scalar(x, 60) for x in o)) or
                    (isinstance(o, dict) and 0 < len(o) <= 50 and all(_str(k, 60) and _scalar(v, 60) for k, v in o.items()))):
                e.append(f"{where}: 'options' is a list, or labels → values (at most 50)")
    for k, items, n_ in (("tips", 10, 300),):
        if k in r and not _strs(r[k], items, n_):
            e.append(f"'{k}': at most {items} short texts")
    if "host_steps" in r:
        hs = r["host_steps"]
        if not (isinstance(hs, list) and len(hs) <= 5 and all(isinstance(h, dict) and set(h) <= {"if_on", "text"}
                                                               and _str(h.get("text"), 600) and _strs(h.get("if_on", []), 5, 40)
                                                               for h in hs)):
            e.append("'host_steps': at most 5, each with a 'text' and an optional 'if_on' list")
    c = r.get("compose")
    if not isinstance(c, dict) or not isinstance(c.get("services"), dict) or not 0 < len(c["services"]) <= 10:
        e.append("'compose' needs 'services' (1 to 10)")
    else:
        for sname, svc in c["services"].items():
            where = f"service {str(sname)[:40]!r}"
            if not isinstance(sname, str) or not SERVICE_NAME.match(sname):
                e.append(f"{where}: a plain lowercase name"); continue
            if not isinstance(svc, dict):
                e.append(f"{where}: must be a mapping"); continue
            if not _str(svc.get("image"), 200):
                e.append(f"{where}: needs an 'image'")
            for k in ("ports", "volumes", "cap_add", "devices", "depends_on"):
                if k in svc and not (isinstance(svc[k], list) and len(svc[k]) <= 20 and all(_str(x, 200) or _int(x, 1, 65535) for x in svc[k])):
                    e.append(f"{where}: '{k}' must be a list of short values")
            for k in ("restart", "network_mode", "user"):
                if k in svc and not _str(svc[k], 40):
                    e.append(f"{where}: '{k}' must be a short text")
            if "environment" in svc and not (isinstance(svc["environment"], dict) and len(svc["environment"]) <= 60 and
                                             all(isinstance(k, str) and ENV_NAME.match(k) and _scalar(v) for k, v in svc["environment"].items())):
                e.append(f"{where}: 'environment' maps NAMES to plain values")
            if "command" in svc and not (_str(svc["command"], 500) or _strs(svc["command"], 30, 200)):
                e.append(f"{where}: 'command' is a text or a list of texts")
            if "deploy" in svc and not (isinstance(svc["deploy"], dict) and _plain(svc["deploy"], 3)):
                e.append(f"{where}: 'deploy' holds plain values only")
            if "healthcheck" in svc and not (isinstance(svc["healthcheck"], dict) and _plain(svc["healthcheck"], 2)):
                e.append(f"{where}: 'healthcheck' holds plain values only")
    u = r.get("update")
    if not isinstance(u, dict) or set(u) - {"main", "tags", "health", "major"}:
        e.append("'update' holds main, tags, health and major")
    else:
        if not _str(u.get("main"), 40) or not _str(u.get("tags"), 120):
            e.append("update: 'main' and 'tags' must be short texts")
        h = u.get("health", {})
        if not (isinstance(h, dict) and set(h) <= {"check", "service", "path", "answer_below", "wait"} and _str(h.get("check"), 30)
                and _str(h.get("service", ""), 40) and _str(h.get("path", ""), 200)
                and _int(h.get("answer_below", 400), 200, 599) and _int(h.get("wait", 60), 0, 3600)):
            e.append("update.health: check, and optionally service, path, answer_below, wait")
        m = u.get("major", {})
        if not (isinstance(m, dict) and set(m) <= {"dump", "rollback", "one_at_a_time", "wait"} and isinstance(m.get("dump", {}), dict)
                and set(m.get("dump", {})) <= {"kind", "service", "folder"}
                and all(_str(v, 40) for v in m.get("dump", {}).values()) and _str(m.get("rollback", ""), 20)
                and isinstance(m.get("one_at_a_time", True), bool)):
            e.append("update.major: dump {kind, service or folder}, rollback, one_at_a_time")
    return e


def _plain(node, depth):
    """Nested mappings/lists of plain values, not too deep or wide (deploy, healthcheck)."""
    if depth < 0:
        return False
    if isinstance(node, dict):
        return len(node) <= 20 and all(_str(k, 40) and _plain(v, depth - 1) for k, v in node.items())
    if isinstance(node, list):
        return len(node) <= 20 and all(_plain(v, depth - 1) for v in node)
    return _scalar(node)


# ---- meaning

def walk(node, path=""):
    """Every string in a part of the recipe, with where it sits."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def safe_pattern(p):
    """A tag pattern from a repository: compiled, and without the shapes that can make matching take forever
    (a repeated group, a back-reference) — tag patterns never need them."""
    if re.search(r"\)\s*[*+{?]|\\[1-9]|\(\?[=!<P]", p):
        return None, "update.tags: no repeated groups, back-references or look-arounds"
    try:
        return re.compile(p), ""
    except re.error as e:
        return None, f"update.tags isn't a valid pattern: {e}"


def check_slots(slots, err, warn):
    for name, s in slots.items():
        t = s.get("type")
        if t not in TYPES:
            err.append(f"slot {name}: unknown type {t!r}"); continue
        if s.get("suggest") and s["suggest"] not in TYPES[t]:
            err.append(f"slot {name}: suggestion {s['suggest']!r} doesn't fit a {t}")
        q, h = s.get("question", ""), s.get("help", "")
        if not q or not h:
            err.append(f"slot {name}: needs a 'question' and a 'help' in plain words")
        if len(q) > 70 or len(h) > 260:
            warn.append(f"slot {name}: question or help is long (aim: question ≤ 70, help ≤ 260 characters)")
        if JARGON.search(q):
            warn.append(f"slot {name}: the question uses a technical word ({JARGON.search(q).group(0)!r}) — say what it's for instead")
        if t == "secret":
            src = s.get("source", "generate")
            if src not in ("generate", "ask"):
                err.append(f"slot {name}: a secret's source is 'generate' or 'ask'")
            if src == "generate" and not 16 <= s.get("length", 0) <= 128:
                err.append(f"slot {name}: a generated secret needs a length of 16–128")
        if t == "choice":
            opts = s.get("options") or []
            if s.get("default") not in (list(opts) if isinstance(opts, dict) else opts):
                err.append(f"slot {name}: the default isn't one of the options")
        elif "options" in s:
            err.append(f"slot {name}: only a choice has options")
        if t == "toggle":
            if not isinstance(s.get("default"), bool) or "on" not in s or "off" not in s:
                err.append(f"slot {name}: a toggle needs a true/false default and fixed 'on' and 'off' values")
            for side in ("on", "off"):
                for m in SLOT.finditer(str(s.get(side, ""))):
                    ref = slots.get(m.group(1), {})
                    if ref.get("type") in (None, "secret", "toggle"):
                        err.append(f"slot {name}: its '{side}' value may only use other plain gaps, not {m.group(1)!r}")
        elif "on" in s or "off" in s:
            err.append(f"slot {name}: only a toggle has 'on' and 'off'")
        if t != "toggle" and "default" in s and not s.get("asked_if") and t not in ("folder", "secret", "user", "timezone") \
                and not valid(s, s["default"]):
            err.append(f"slot {name}: its default isn't a valid answer")
        if "under" in s:
            base = slots.get(s["under"], {})
            if base.get("type") != "folder" or "under" in base or t != "folder" or not s.get("sub"):
                err.append(f"slot {name}: 'under' needs a folder gap of its own, a main folder gap, and a 'sub'")
            elif base.get("suggest") == "yours":
                err.append(f"slot {name}: nothing goes 'under' a folder of yours: it's only read, never made or written")
        elif t == "folder" and s.get("suggest") not in ("app-folder", "yours"):
            err.append(f"slot {name}: a folder gap says 'suggest: app-folder' (made for the app) or 'suggest: yours' "
                       "(one you already have, read only)")
        if t == "folder" and s.get("suggest") == "yours":
            bad = sorted(k for k in ("sub", "default", "asked_if", "advanced") if k in s)
            if bad:
                err.append(f"slot {name}: a folder of yours is always asked, with no {', '.join(bad)}")
        if "asked_if" in s and slots.get(s["asked_if"], {}).get("type") != "toggle":
            err.append(f"slot {name}: 'asked_if' must name a toggle")


def check(r, repo_id=None):
    """(errors, notes) for one recipe (a parsed mapping). Errors = refused; notes = shown to the author only."""
    err = shape(r)
    if err:
        return err, []
    try:
        return _check(r, repo_id)
    except Exception as e:          # a case shape() didn't foresee: still a refusal, never a crash (and a bug to fix)
        return [f"internal: the checker couldn't read this recipe ({type(e).__name__}) — refused"], []


def _check(r, repo_id):
    err, warn = [], []
    if repo_id and not r["id"].startswith(repo_id + "."):
        err.append(f"id {r['id']} doesn't start with the repository's id '{repo_id}.'")
    slots = r["slots"]
    check_slots(slots, err, warn)
    elevated = (r.get("needs") or {}).get("elevated") or {}
    for e, why in elevated.items():
        if e not in ELEVATED:
            err.append(f"needs.elevated: {e!r} can never be granted")
        elif len(why) < 20:
            err.append(f"needs.elevated: {e} needs a reason in plain words")
    allowed = {}
    for e in elevated:
        if e in ELEVATED:
            key, val = ELEVATED[e]; allowed.setdefault(key, set()).add(val)
    services = r["compose"]["services"]
    if set(r["compose"]) - {"services"}:
        err.append(f"compose: only 'services' is allowed (found {sorted(map(str, set(r['compose']) - {'services'}))})")
    used = {s["under"] for s in slots.values() if "under" in s} | {s["asked_if"] for s in slots.values() if "asked_if" in s}
    in_toggles = set()
    for s in slots.values():
        if s.get("type") == "toggle":
            for side in ("on", "off"):
                in_toggles |= {m.group(1) for m in SLOT.finditer(str(s.get(side, "")))}
    used |= in_toggles
    yours = {n for n, s in slots.items() if s.get("type") == "folder" and s.get("suggest") == "yours"}
    if len(yours) > YOURS_MAX:
        err.append(f"at most {YOURS_MAX} folders of yours per app ({len(yours)} declared)")
    for path, text in walk(r["compose"]):
        for m in SLOT.finditer(text):
            base, attr = m.groups(); used.add(base)
            if base in yours and not re.match(r"^\.services\.[^.\[]+\.volumes\[[0-9]+\]$", path):
                err.append(f"{path}: '{{{{{base}}}}}' is a folder of yours: it may only be a volume")
            if base not in slots:
                err.append(f"{path}: '{{{{{base}}}}}' isn't declared: refused")
            elif attr and not (slots[base]["type"] == "user" and attr in ("uid", "gid")):
                err.append(f"{path}: '.{attr}' isn't allowed on a {slots[base]['type']}")
            elif slots[base]["type"] == "secret" and not (".environment." in path and WHOLE.match(text)):
                err.append(f"{path}: a secret may only be a whole environment value (so it can go to .env)")
            elif "asked_if" in slots[base]:
                err.append(f"{path}: '{{{{{base}}}}}' is only asked when a switch is on: use it inside that switch's 'on' value")
    for path, text in walk(r.get("tips", []) + [h.get("text", "") for h in r.get("host_steps", [])]):
        for m in SLOT.finditer(text):
            if slots.get(m.group(1), {}).get("type") in (None, "secret"):
                err.append(f"tips/host_steps: '{{{{{m.group(1)}}}}}' isn't a gap they may show")
    for h in r.get("host_steps", []):
        for t in h.get("if_on", []):
            if slots.get(t, {}).get("type") != "toggle":
                err.append(f"host_steps: 'if_on' names {t!r}, not a toggle")
    for name in set(slots) - used:
        warn.append(f"slot {name} is declared but never used")
    for sname, svc in services.items():
        extra = set(svc) - SERVICE_KEYS - set(allowed)
        if extra:
            err.append(f"{sname}: not allowed: {sorted(map(str, extra))} (privileged, pid, security_opt… are never accepted;"
                       f" host network, NET_ADMIN, NET_RAW and the tun device only when declared in needs.elevated)")
        for key in set(allowed) & set(svc):
            vals = {svc[key]} if isinstance(svc[key], str) else set(map(str, svc[key]))
            if vals - allowed[key]:
                err.append(f"{sname}: {key} {sorted(vals - allowed[key])} isn't declared in needs.elevated")
        img = svc.get("image", "")
        if not re.match(r"^[a-z0-9.\-/]+:[A-Za-z0-9._\-]+$", img):
            err.append(f"{sname}: the image needs a plain name and a tag ({img[:80]!r}); the digest is pinned at install")
        if svc.get("network_mode") == "host" and svc.get("ports"):
            err.append(f"{sname}: ports mean nothing on the host network: remove them")
        for p in svc.get("ports", []):
            m = WHOLE.match(str(p).split(":")[0])
            if not (m and slots.get(m.group(1), {}).get("type") == "port"):
                err.append(f"{sname}: port {str(p)[:40]!r}: the outside port must be a port gap")
        for v in svc.get("volumes", []):
            m = re.match(r"^\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}(/[a-z0-9_\-]+)*$", str(v).split(":")[0])
            if not (m and slots.get(m.group(1), {}).get("type") == "folder"):
                err.append(f"{sname}: volume {str(v)[:60]!r}: the outside path must be a folder gap (no fixed paths, no Docker socket)")
            elif str(v).count(":") > 2 or (str(v).count(":") == 2 and str(v).rsplit(":", 1)[1] not in ("ro", "rw")):
                err.append(f"{sname}: volume {str(v)[:60]!r}: only ':ro' or ':rw' may follow the inside path")
            elif m.group(1) in yours and not re.match(r"^\{\{\s*[a-z_][a-z0-9_]*\s*\}\}:/[A-Za-z0-9._/-]+:ro$", str(v)):
                err.append(f"{sname}: volume {str(v)[:60]!r}: a folder of yours is mounted whole and read only: "
                           f"'{{{{{m.group(1)}}}}}:/inside/path:ro'")
        if "user" in svc:
            m = USER_FORM.match(svc["user"])
            if not (m and slots.get(m.group(1), {}).get("type") == "user"):
                err.append(f"{sname}: user must be \"{{{{<a user gap>.uid}}}}:{{{{<a user gap>.gid}}}}\" — your own account, "
                           "never a fixed number or root")
        if set(svc.get("deploy", {})) - {"resources"}:
            err.append(f"{sname}: deploy may only hold resources")
        for d in svc.get("depends_on", []):
            if d not in services:
                err.append(f"{sname}: depends on unknown service {str(d)[:40]}")
    for key in allowed:
        if not any(key in s for s in services.values()):
            warn.append(f"needs.elevated declares {key} but no service uses it")
    u = r["update"]
    if u.get("main") not in services:
        err.append(f"update.main {str(u.get('main'))[:40]!r} isn't a service")
    else:
        pat, why = safe_pattern(u.get("tags", "$^"))
        tag = services[u["main"]].get("image", ":").rsplit(":", 1)[-1]
        if not pat:
            err.append(why)
        elif not pat.match(tag[:128]):
            err.append(f"update.tags doesn't match the main image's own tag {tag[:60]!r}")
    if (u.get("health") or {}).get("check") not in HEALTH:
        err.append(f"update.health: unknown check {str((u.get('health') or {}).get('check'))[:30]!r} (needs a newer gate)")
    major = u.get("major") or {}
    d = major.get("dump", {})
    if d.get("kind") not in DUMPS:
        err.append(f"update.major.dump: unknown kind {str(d.get('kind'))[:30]!r}")
    if d.get("kind") in ("postgres", "mariadb") and d.get("service") not in services:
        err.append("update.major.dump: its service isn't in the recipe")
    if d.get("kind") == "stop-and-copy" and slots.get(d.get("folder"), {}).get("type") != "folder":
        err.append("update.major.dump: stop-and-copy needs a folder gap")
    if major.get("rollback") not in ROLLBACK:
        err.append(f"update.major.rollback: {str(major.get('rollback'))[:20]!r} isn't 'image' or 'none'")
    return err, warn


def checked(r, repo_id=None):
    """The recipe if it passes, else Refused with every reason (fill and permissions only work on a passed recipe)."""
    err, _ = check(r, repo_id)
    if err:
        raise Refused("; ".join(err))
    return r


# ---- answers

def valid(slot, value):
    t = slot["type"]
    if t == "folder":
        return isinstance(value, str) and value.startswith("/") and len(value) < 300 and ".." not in value.split("/") \
            and not UNSAFE.search(value)
    if t == "port":
        return _int(value, 1024, 65535)
    if t == "number":
        return _int(value, -10**9, 10**9)
    if t in ("text", "url", "timezone") or (t == "secret" and slot.get("source") == "ask"):
        return isinstance(value, str) and 0 < len(value) < 200 and not UNSAFE.search(value) and " " not in value.strip()
    if t == "choice":
        o = slot.get("options") or []
        return isinstance(value, (str, int)) and not isinstance(value, bool) and value in (o if isinstance(o, list) else list(o))
    if t == "toggle":
        return isinstance(value, bool)
    if t == "networks":                 # private address ranges only: never "the whole internet"
        try:
            return isinstance(value, list) and 0 < len(value) <= 10 and all(
                isinstance(v, str) and ipaddress.ip_network(v, strict=True).is_private for v in value)
        except ValueError:
            return False
    if t == "user":
        return isinstance(value, dict) and set(value) == {"uid", "gid"} and all(_int(value[k], 0, 1 << 31) for k in ("uid", "gid"))
    return False                        # a type this code doesn't know never gets an answer through


def fill(r, answers, rng=secrets):
    """Fill a passed recipe in as DATA: each string rebuilt from its parts, the result written by the YAML library.
    → (compose text, {ENV: secret}, tips, steps by hand). A bad answer → Refused, naming the gap."""
    compose, env, tips, steps = _fill(r, answers, rng, for_gate=False)
    return yaml.safe_dump(compose, sort_keys=False, allow_unicode=True), env, tips, steps


def fill_install(r, answers):
    """For an install through the gate (gate 1.5): → (compose as data, {ENV: {"generate": n} | {"value": pasted}}, tips,
    steps). No password is made here: the gate makes generated ones on the machine itself; a pasted one travels to it
    on standard input, never in a request line."""
    return _fill(r, answers, None, for_gate=True)


def _fill(r, answers, rng, for_gate):
    checked(r)
    if not isinstance(answers, dict):
        raise Refused("the answers aren't a mapping")
    slots, env, vals = r["slots"], {}, {}

    def answer(name, s, default):
        v = answers.get(name, default)
        if not valid(s, v):
            raise Refused(f"answer for {name} refused: {str(v)[:60]!r}")
        return v

    for name, s in slots.items():           # plain gaps first; folders under a main folder and toggles after
        if s["type"] == "secret" and s.get("source", "generate") == "generate":
            vals[name] = {"generate": s["length"]} if for_gate else \
                "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(s["length"]))
            continue
        if "under" in s or s["type"] == "toggle":
            continue
        if "asked_if" in s and not answers.get(s["asked_if"], slots[s["asked_if"]]["default"]):
            vals[name] = None; continue
        v = answer(name, s, s.get("default"))
        if s["type"] == "choice" and isinstance(s["options"], dict):
            v = s["options"][v]
        vals[name] = ",".join(v) if s["type"] == "networks" else v
    for name, s in slots.items():
        if "under" in s:
            vals[name] = answer(name, s, vals[s["under"]] + "/" + s["sub"])
    for name, s in slots.items():
        if s["type"] == "toggle":
            v = answer(name, s, s["default"])
            vals[name] = SLOT.sub(lambda m: str(vals[m.group(1)]), str(s["on"] if v else s["off"]))

    def sub(text):
        m = WHOLE.match(text)
        if m and slots[m.group(1)]["type"] == "secret":
            key, v = m.group(1).upper(), vals[m.group(1)]
            env[key] = v if not for_gate or isinstance(v, dict) else {"value": v}
            return "${" + key + "}"
        return " ".join(SLOT.sub(lambda m: str(vals[m.group(1)][m.group(2)] if m.group(2) else vals[m.group(1)]), text).split()) \
            if SLOT.search(text) else text

    def rebuild(node):
        if isinstance(node, dict):
            return {k: rebuild(v) for k, v in node.items()}
        if isinstance(node, list):
            return [rebuild(v) for v in node]
        return sub(node) if isinstance(node, str) else node

    compose = rebuild(r["compose"])        # ${NAME} is filled by Compose from the project's own .env, per value
    tips = [rebuild(t) for t in r.get("tips", [])]
    steps = [rebuild(h["text"]) for h in r.get("host_steps", [])
             if any(answers.get(t, slots[t]["default"]) for t in h.get("if_on", []))]
    return compose, env, tips, steps


def permissions(r):
    """What the app would get, worked out from a passed recipe — never from text its author wrote.
    Each line: (kind, what, when) — when = "always" or the switch it depends on. The reasons shown beside the extra
    access come from needs.elevated; the list itself does not."""
    checked(r)
    slots, services, out = r["slots"], r["compose"]["services"], []
    toggles = {n: s for n, s in slots.items() if s["type"] == "toggle"}
    folders = {}
    for svc in services.values():
        for v in svc.get("volumes", []):
            parts = str(v).split(":")
            name = WHOLE.match(re.sub(r"/[a-z0-9_\-/]+$", "", parts[0])).group(1)
            base = slots[name].get("under", name)
            folders.setdefault(base, set()).add("read only" if parts[-1] == "ro" else "read and change")
    for base, modes in folders.items():         # made for the app (app-folder, or inside one) vs one of yours it may use
        if slots[base].get("suggest") == "yours":
            out.append(("folder", f"reads a folder you choose ({slots[base]['question'].rstrip('?')}) — read only; it can't "
                        "change it. You approve it on the machine first", "always"))
            continue
        own = slots[base].get("suggest") == "app-folder"
        out.append(("folder", f"{'its own folder' if own else 'a folder you choose'} ({slots[base]['question'].rstrip('?')}) — "
                    + " / ".join(sorted(modes)), "always"))
    if services and all("user" in svc for svc in services.values()):
        out.append(("account", "runs as your own account, not as the machine's administrator (root)", "always"))
    if any(svc.get("network_mode") == "host" for svc in services.values()):
        out.append(("network", "your home network directly (like a device plugged into the router)", "always"))
    else:
        n = sum(len(svc.get("ports", [])) for svc in services.values())
        out.append(("network", f"{n} address{'es' if n != 1 else ''} at home, for you or your other apps to reach it" if n else "no address at home", "always"))
    for t, s in toggles.items():
        on = str(s["on"])
        nets = [m.group(1) for m in SLOT.finditer(on) if slots.get(m.group(1), {}).get("type") == "networks"]
        if nets:                                         # computed: a home address range goes into the setting
            out.append(("network", "it can let your devices reach other things at home (the range you choose)", t))
        elif on:                                         # any other switch: named by its own question, nothing claimed
            out.append(("setting", f"you choose: “{s['question']}”", t))
    out.append(("internet", "it can reach the internet (every app can, unless it's cut off)", "always"))
    for e in ((r.get("needs") or {}).get("elevated") or {}):
        out.append(("extra", ELEVATED_WORDS[e], "always"))
    for s in slots.values():
        if s["type"] == "secret":
            out.append(("secret", "a password or key you paste in (kept in .env, never shown)" if s.get("source") == "ask"
                        else "passwords made for it (kept in .env, never shown)", "always"))
    out = list(dict.fromkeys(out))
    out.append(("outside", "nothing from outside home: making it reachable from outside is a separate step, by hand", "always"))
    return out
