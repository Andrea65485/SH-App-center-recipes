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

import ipaddress, json, re, secrets, string, urllib.parse

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
INSIDE = {"json", "url", "plain"}     # 0.9.6: how each answer is written into a longer value (secret-in-value-design.md)
IN_VALUE = {"secret", "text", "url", "choice"}       # the gaps that may go inside one: answers typed or chosen
GATE_SECRET = re.compile(r"^[A-Z][A-Z0-9_]{0,40}$")   # the gate's own rule for a .env name (gate 1.5+)
VALUE_MIN, VALUE_MAX = 8, 512         # the gate takes 8–512 printable characters, no $
ENCODE = {"json": lambda x: json.dumps(x)[1:-1],                      # " → \", \ → \\, the rest as \uXXXX: one ASCII line
          "url": lambda x: urllib.parse.quote(x, safe=""),            # @ : / and the rest can't break the address
          "plain": lambda x: x}
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
             "under", "sub", "asked_if", "prefix", "kind", "shape"}
SECRET_KINDS = {"password"}          # 0.9.6: an ask secret with kind: password is one you choose, not a key of yours
# 0.9.6: a key some apps take only in one shape. A closed list, never a recipe's own pattern. Refused here first: the app
# itself would print what was typed in its log (the DDNS updater does), and that may be another password pasted by mistake.
SHAPES = {"uuid": (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
                   "36 characters in the shape xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx, made of digits and the small letters a to f"),
          "hex32": (re.compile(r"[0-9a-f]{32}"), "32 characters, made of digits and the small letters a to f")}
NEEDS_KEYS = {"platforms", "memory_mb", "elevated", "internet", "https"}
# ---- format 2 (owner, 7 Nov: "more metadata for the store … categories or info for using filters"). Format 1 stays as
# it is (today's readers know only it); format 2 adds the fields below, all checked here, and optional pasted secrets.
SCHEMAS = (1, 2)
TOP_KEYS_2 = TOP_KEYS | {"also", "licence", "use_from"}
# One fixed list (format 1's free text had drifted into 16 spellings). The words are the Store's filter labels.
CATEGORIES = {"media": "Films, TV and audiobooks", "music": "Music", "photos": "Photos", "games": "Games",
              "reading": "News, bookmarks and books", "documents": "Documents and PDFs", "files": "Files, sync and backups",
              "smart-home": "Smart home", "household": "Household", "network": "Network and remote access",
              "security": "Passwords and logins", "monitoring": "Monitoring and alerts", "development": "Code",
              "automation": "Automation", "tools": "Small tools"}
USE_FROM = {"browser": "a browser", "desktop-app": "an app on a computer", "phone-app": "an app on a phone",
            "devices": "other devices and apps (no page of its own)"}
INTERNET = {"none": "doesn't need the internet", "optional": "uses the internet for some features",
            "needed": "needs the internet to work"}
LICENCE = re.compile(r"^(LicenseRef-[A-Za-z0-9.-]{1,40}|[A-Za-z0-9][A-Za-z0-9.+-]{1,49})$")      # an SPDX name
# Open source = one of these (OSI-approved) — as the recipe DECLARES it: shown as declared, never as checked.
OPEN_SOURCE = {"AGPL-3.0-only", "AGPL-3.0-or-later", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
               "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later", "MIT", "Apache-2.0",
               "BSD-2-Clause", "BSD-3-Clause", "MPL-2.0", "ISC", "EPL-2.0", "EUPL-1.2", "Unlicense", "0BSD", "Zlib"}


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


def _entry_shape(v):
    """0.9.6, format 2: an environment value with gaps inside — {inside, value} or {inside, by, cases}."""
    if not (isinstance(v, dict) and isinstance(v.get("inside"), str) and v["inside"] in INSIDE):
        return False
    if set(v) == {"inside", "value"}:
        return _str(v["value"], 2000)
    c = v.get("cases")
    return (set(v) == {"inside", "by", "cases"} and _str(v["by"], 40) and isinstance(c, dict) and 1 <= len(c) <= 40
            and all(_str(k, 60) and _str(x, 2000) for k, x in c.items()))


def _asked_if_shape(a):
    """A switch's name, or (0.9.6, format 2) {a choice's name: [the values it's asked for]}."""
    if isinstance(a, str):
        return len(a) <= 40
    return (isinstance(a, dict) and len(a) == 1 and all(
        _str(k, 40) and isinstance(vs, list) and 1 <= len(vs) <= 40 and all(_str(x, 60) for x in vs)
        and len(set(vs)) == len(vs) for k, vs in a.items()))


def entries(compose):
    """The environment values given as a mapping (0.9.6): (service, NAME, entry)."""
    for sname, svc in (compose.get("services") or {}).items():
        env = svc.get("environment") if isinstance(svc, dict) else None
        for k, v in (env.items() if isinstance(env, dict) else ()):
            if isinstance(v, dict):
                yield sname, k, v


def templates(e):
    """(case or None, text) for each text an entry can become."""
    return [(None, e["value"])] if "value" in e else list(e["cases"].items())


def choice_values(s):
    """A choice's stored values (what goes into the file), not its labels."""
    o = s.get("options") or []
    return list(o.values()) if isinstance(o, dict) else list(o)


def chosen(slots, name, answers):
    """A choice's stored value for these answers."""
    s = slots[name]
    v = answers.get(name, s.get("default"))
    if isinstance(s.get("options"), dict):
        return s["options"].get(v) if isinstance(v, str) else None
    return v


def asked_by(a):
    """(choice, values) for an asked_if naming a choice's values; None for a switch's name or none."""
    return next(iter(a.items())) if isinstance(a, dict) else None


def is_asked(slots, s, answers):
    """Whether this gap is asked for these answers: always, while its switch is on, or for some answers of a choice."""
    a = s.get("asked_if")
    if a is None:
        return True
    if isinstance(a, str):
        return bool(answers.get(a, slots[a]["default"]))
    c, vals = asked_by(a)
    return chosen(slots, c, answers) in vals


def value_problem(v):
    """What would make the gate or Docker Compose refuse or change a filled value; None when it's fine."""
    if len(v) > VALUE_MAX:
        return f"would be {len(v)} characters: {len(v) - VALUE_MAX} more than the {VALUE_MAX} the machine takes"
    if len(v) < VALUE_MIN:
        return f"would be shorter than the {VALUE_MIN} characters the machine takes"
    if not v.isprintable() or "$" in v:
        return "would hold a line break, a $ or another character the machine refuses"
    if " #" in v or v != v.strip():
        return "would be cut short by Docker Compose (a ' #', or a space at the start or end)"
    if v[0] in "\"'`":                 # the gate writes NAME=value unquoted: Compose would read a leading quote as quoting
        return "would start with a quote mark, which Docker Compose reads as quoting"
    return None


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
    if r.get("schema") not in SCHEMAS or isinstance(r.get("schema"), bool):
        return [f"schema {r.get('schema')!r} unknown: refused"]
    v2 = r["schema"] == 2
    for k in sorted(set(r) - (TOP_KEYS_2 if v2 else TOP_KEYS), key=str):
        e.append(f"unknown field {str(k)[:40]!r}")
    for k in ("id", "name", "summary", "version"):
        if not _str(r.get(k), 300) or not r.get(k):
            e.append(f"'{k}' must be a short text")
    if _str(r.get("id")) and not ID.match(r["id"]):
        e.append("'id' must look like <repository>.<app> (lowercase letters, digits, dashes)")
    if v2:
        e += shape_2(r)
    elif "category" in r and not _str(r["category"], 40):
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
            if k == "internet" and v2:
                continue                    # format 2: a level and a reason (shape_2)
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
                      ("under", 40), ("prefix", 60), ("kind", 20), ("shape", 20)):
            if k in s and not _str(s[k], n_):
                e.append(f"{where}: '{k}' must be a text")
        if "asked_if" in s and not _asked_if_shape(s["asked_if"]):
            e.append(f"{where}: 'asked_if' is a switch's name, or {{a choice's name: [the answers it's asked for]}}")
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
                                             all(isinstance(k, str) and ENV_NAME.match(k) and (_scalar(v) or _entry_shape(v))
                                                 for k, v in svc["environment"].items())):
                e.append(f"{where}: 'environment' maps NAMES to plain values (format 2 also: a value with gaps inside, "
                         "as inside + value, or inside + by + cases)")
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
        if "kind" in s and not (t == "secret" and s.get("source") == "ask" and s["kind"] in SECRET_KINDS):
            err.append(f"slot {name}: 'kind: password' is only for a secret you type in (source: ask) — a password you "
                       "choose yourself, not a key from another service")
        if "shape" in s and not (t == "secret" and s.get("source") == "ask" and isinstance(s["shape"], str)
                                and s["shape"] in SHAPES):
            err.append(f"slot {name}: 'shape' is only for a secret you type in (source: ask), and is one of: "
                       + ", ".join(SHAPES))
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
                    if ref.get("type") in (None, "secret", "toggle") or isinstance(ref.get("asked_if"), dict):
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
        a = s.get("asked_if")
        if isinstance(a, str) and slots.get(a, {}).get("type") != "toggle":
            err.append(f"slot {name}: 'asked_if' must name a toggle")
        elif isinstance(a, dict):                         # 0.9.6: asked only for some answers of a choice
            c, vals = asked_by(a)
            ref = slots.get(c, {})
            if ref.get("type") != "choice" or "asked_if" in ref or not all(isinstance(x, str) for x in choice_values(ref)):
                err.append(f"slot {name}: 'asked_if' names {c!r}: not a choice that is always asked (with text values)")
            elif set(vals) - set(choice_values(ref)):
                err.append(f"slot {name}: 'asked_if' lists answers {c!r} doesn't have: {sorted(set(vals) - set(choice_values(ref)))}")
            if t not in IN_VALUE or (t == "secret" and s.get("source") != "ask"):
                err.append(f"slot {name}: only a secret you paste, a text, an address or a choice can be asked for some "
                           "answers of a choice (it goes inside a value with gaps)")


def shape_2(r):
    """Format 2's own fields: one category from the list (+ up to 2 more), the licence's SPDX name, how it's used, and
    the internet as a level with its reason."""
    e = []
    if r.get("category") not in CATEGORIES:
        e.append(f"'category' must be one of: {', '.join(CATEGORIES)}")
    also = r.get("also", [])
    if not (isinstance(also, list) and len(also) <= 2 and all(a in CATEGORIES for a in also)
            and len(set(also)) == len(also) and r.get("category") not in also):
        e.append("'also': up to 2 more categories from the same list, different from 'category'")
    if not (_str(r.get("licence"), 60) and LICENCE.match(r["licence"])):
        e.append("'licence': the app's licence as its SPDX name (e.g. AGPL-3.0-only, MIT, CC-BY-NC-SA-4.0)")
    u = r.get("use_from")
    if not (isinstance(u, list) and 1 <= len(u) <= len(USE_FROM) and all(x in USE_FROM for x in u) and len(set(u)) == len(u)):
        e.append(f"'use_from': 1–{len(USE_FROM)} of {', '.join(USE_FROM)}")
    i = (r.get("needs") or {}).get("internet") if isinstance(r.get("needs"), dict) else None
    if not (isinstance(i, dict) and set(i) <= {"level", "why"} and i.get("level") in INTERNET
            and (_str(i.get("why"), 300) and i.get("why") if i.get("level") != "none" else ("why" not in i or _str(i["why"], 300)))):
        e.append("needs.internet: {level: none|optional|needed, why: what it uses the internet for} (why: unless none)")
    return e


def always(slots, a, among):
    """Whether something asked under `a` is there for every answer: no asked_if, or (0.9.6) a choice whose every
    answer asks one of `among` (the asked_ifs of the same kind of thing)."""
    if a is None:
        return True
    if isinstance(a, str):
        return False
    ch = asked_by(a)[0]
    got = {v for x in among if isinstance(x, dict) and asked_by(x)[0] == ch for v in asked_by(x)[1]}
    return got >= set(choice_values(slots[ch]))


def facts(r):
    """The Store's filter facts, worked out from a passed recipe (format 1 or 2) — most from what it already says, so
    they can't drift from it. Format 1 has only its free-text category: it goes under 'other'."""
    checked(r)
    v2, slots, n = r["schema"] == 2, r["slots"], r.get("needs") or {}
    asks = [s for s in slots.values() if s["type"] == "secret" and s.get("source") == "ask"
            and s.get("kind") != "password"]       # a password you choose isn't a key from another service (0.9.6)
    return {"categories": ([r["category"]] + r.get("also", [])) if v2 else ["other"],
            "pi": "linux/arm64" in (n.get("platforms") or []),
            "memory_mb": n.get("memory_mb"),
            "own_key": "needed" if any(always(slots, s.get("asked_if"), [x.get("asked_if") for x in asks]) for s in asks)
                       else "optional" if asks else "no",
            "your_folders": any(s["type"] == "folder" and s.get("suggest") == "yours" for s in slots.values()),
            "extra_access": bool(n.get("elevated")),
            "licence": r.get("licence"), "open_source": r.get("licence") in OPEN_SOURCE,
            "internet": n["internet"]["level"] if v2 else None,
            "use_from": r.get("use_from", [])}


def check(r, repo_id=None):
    """(errors, notes) for one recipe (a parsed mapping). Errors = refused; notes = shown to the author only."""
    if isinstance(r, dict) and r.get("schema") == UPDATE_ONLY_SCHEMA:     # 0.9.8: update rules only, no install
        return check_update_only(r, repo_id), []
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
    for name, s in slots.items():
        if s.get("type") == "secret" and "asked_if" in s and r["schema"] != 2:
            err.append(f"slot {name}: a secret asked only when a switch is on needs format 2 (schema: 2)")
        if "kind" in s and r["schema"] != 2:
            err.append(f"slot {name}: 'kind' needs format 2 (schema: 2)")
        if isinstance(s.get("asked_if"), dict) and r["schema"] != 2:
            err.append(f"slot {name}: a gap asked for some answers of a choice needs format 2 (schema: 2)")
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
    used = {s["under"] for s in slots.values() if "under" in s} | {
        a if isinstance(a, str) else asked_by(a)[0] for a in (s.get("asked_if") for s in slots.values()) if a}
    in_toggles = set()
    for s in slots.values():
        if s.get("type") == "toggle":
            for side in ("on", "off"):
                in_toggles |= {m.group(1) for m in SLOT.finditer(str(s.get(side, "")))}
    used |= in_toggles
    yours = {n for n, s in slots.items() if s.get("type") == "folder" and s.get("suggest") == "yours"}
    if len(yours) > YOURS_MAX:
        err.append(f"at most {YOURS_MAX} folders of yours per app ({len(yours)} declared)")
    inside = tuple(f".services.{sn}.environment.{k}." for sn, k, _ in entries(r["compose"]))
    check_entries(r, slots, err, used)
    for path, text in walk(r["compose"]):
        if path.startswith(inside or ("\0",)):
            continue                                   # a value with gaps inside: check_entries' rules
        for m in SLOT.finditer(text):
            base, attr = m.groups(); used.add(base)
            if base in yours and not re.match(r"^\.services\.[^.\[]+\.volumes\[[0-9]+\]$", path):
                err.append(f"{path}: '{{{{{base}}}}}' is a folder of yours: it may only be a volume")
            if base not in slots:
                err.append(f"{path}: '{{{{{base}}}}}' isn't declared: refused")
            elif attr and not (slots[base]["type"] == "user" and attr in ("uid", "gid")):
                err.append(f"{path}: '.{attr}' isn't allowed on a {slots[base]['type']}")
            elif isinstance(slots[base].get("asked_if"), dict):
                err.append(f"{path}: '{{{{{base}}}}}' is only asked for some answers of {asked_by(slots[base]['asked_if'])[0]!r}: "
                           "use it inside a value split by that choice (inside, by, cases)")
            elif slots[base]["type"] == "secret" and not (".environment." in path and WHOLE.match(text)):
                err.append(f"{path}: a secret may only be a whole environment value (so it can go to .env)")
            elif "asked_if" in slots[base] and slots[base]["type"] != "secret":
                err.append(f"{path}: '{{{{{base}}}}}' is only asked when a switch is on: use it inside that switch's 'on' value")
    for path, text in walk(r.get("tips", []) + [h.get("text", "") for h in r.get("host_steps", [])]):
        for m in SLOT.finditer(text):
            if slots.get(m.group(1), {}).get("type") in (None, "secret") or isinstance(slots[m.group(1)].get("asked_if"), dict):
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


def check_entries(r, slots, err, used):
    """0.9.6, format 2: environment values with gaps inside (secret-in-value-design.md, draft 3). The whole value goes to
    .env through the gate as one secret; the compose file only gets ${NAME}."""
    taken = {n.upper() for n, s in slots.items() if s.get("type") == "secret"}
    seen, went = set(), set()                         # went: (gap, choice, answer) — where a choice's own questions go
    for sname, k, e in entries(r["compose"]):
        where = f"{sname}.environment.{k}"
        if r["schema"] != 2:
            err.append(f"{where}: a value with gaps inside needs format 2 (schema: 2)"); continue
        if not GATE_SECRET.match(k):
            err.append(f"{where}: its name goes to .env: capitals, digits and _, starting with a capital, at most 41")
        if k in seen or k in taken:
            err.append(f"{where}: another value or a secret already goes to .env as {k}")
        seen.add(k)
        by = e.get("by")
        if by is not None:
            c = slots.get(by, {})
            if c.get("type") != "choice" or "asked_if" in c or not all(isinstance(x, str) for x in choice_values(c)):
                err.append(f"{where}: 'by' names {by!r}: not a choice that is always asked (with text values)"); continue
            used.add(by)
            want, have = set(choice_values(c)), set(e["cases"])
            if want != have:
                err.append(f"{where}: one case per answer of {by!r}"
                           + (f"; missing: {sorted(want - have)}" if want - have else "")
                           + (f"; not one of its answers: {sorted(have - want)}" if have - want else ""))
                continue
        for case, text in templates(e):
            w = where + (f".cases.{case}" if case is not None else ".value")
            if not text.isprintable() or "$" in text:
                err.append(f"{w}: one line, without $ or other characters the machine refuses")
            if " #" in text or text != text.strip():
                err.append(f"{w}: Docker Compose would cut it short (a ' #', or a space at the start or end)")
            if text[:1] in ("\"", "'", "`"):
                err.append(f"{w}: it may not start with a quote mark: Docker Compose would read it as quoting")
            if len(SLOT.sub("", text)) > VALUE_MAX:
                err.append(f"{w}: already longer than {VALUE_MAX} characters before any answer goes in")
            gaps, secret = [], False
            for m in SLOT.finditer(text):
                base, attr = m.groups(); used.add(base); gaps.append(base)
                g = slots.get(base)
                if g is None:
                    err.append(f"{w}: '{{{{{base}}}}}' isn't declared: refused"); continue
                if attr:
                    err.append(f"{w}: '.{attr}' can't go inside a value"); continue
                t, a = g["type"], g.get("asked_if")
                if t not in IN_VALUE or (t == "secret" and g.get("source") != "ask"):
                    err.append(f"{w}: '{{{{{base}}}}}' is a {t}{' made for the app' if t == 'secret' else ''}: only a "
                               "secret you paste, a text, an address or a choice can go inside a value")
                elif isinstance(a, str):
                    err.append(f"{w}: '{{{{{base}}}}}' is only asked when a switch is on: it can't go inside a value")
                elif isinstance(a, dict):
                    ch, vals = asked_by(a)
                    if ch != by:
                        err.append(f"{w}: '{{{{{base}}}}}' is only asked for some answers of {ch!r}: use it in a value "
                                   f"split by that choice (by: {ch})")
                    elif case not in vals:
                        err.append(f"{w}: '{{{{{base}}}}}' isn't asked when {ch!r} is {case!r}")
                    else:
                        went.add((base, ch, case))
                secret = secret or (t == "secret" and g.get("source") == "ask")
            if not secret:
                err.append(f"{w}: holds no secret you paste: write it as a plain value")
            if e["inside"] == "json":                 # valid JSON once filled, each gap inside a string value
                marks = [f"zq{i}gapzq" for i in range(len(gaps))]
                it = iter(marks)
                try:
                    doc = json.loads(SLOT.sub(lambda m: next(it), text))
                except ValueError:
                    err.append(f"{w}: isn't valid JSON (inside: json)"); continue
                strings = []
                def values(x):
                    if isinstance(x, dict):
                        for v in x.values(): values(v)
                    elif isinstance(x, list):
                        for v in x: values(v)
                    elif isinstance(x, str):
                        strings.append(x)
                values(doc)
                if sum(v.count(mk) for v in strings for mk in marks) != len(marks):
                    err.append(f"{w}: each gap must sit inside a JSON text value, between quotes (inside: json)")
    for n, g in slots.items():                        # each question a choice asks is used whenever it's asked
        a = g.get("asked_if")
        if isinstance(a, dict) and n in used:
            ch, vals = asked_by(a)
            idle = [v for v in vals if (n, ch, v) not in went]
            if idle:
                err.append(f"slot {n}: asked when {ch!r} is {idle}, but no value uses it then")


# ---- format 3 (0.9.8, owner 9 Nov): update rules for an app installed by hand ("installed by hand · matched").
# No compose, no gaps, no install: only which images it is for, and the update rules in the same words the updater's
# own built-in recipes use (local-recipes/*/recipe.yaml), checked by the same code below. The machine, project, service
# and container never come from here: they stay in the updater's own bindings.
UPDATE_ONLY_SCHEMA = 3
UPDATE_ONLY_KEYS = {"schema", "id", "name", "summary", "kind", "match", "update"}
UPDATE_ONLY_OPTIONAL = {"links", "pictures", "category"}
IMAGE_NAME = re.compile(r"^(?:[a-z0-9][a-z0-9-]{0,40}(?:\.[a-z0-9][a-z0-9-]{0,40}){1,4}(?::[0-9]{2,5})?/)?"   # a registry host: dotted
                        r"[a-z0-9]{1,30}(?:(?:[._]|__|-+)[a-z0-9]{1,30}){0,8}(?:/[a-z0-9]{1,30}(?:(?:[._]|__|-+)[a-z0-9]{1,30}){0,8}){0,3}$")
U_VERSION = {"compare", "show-only"}
U_HEALTH = {"none", "app-status", "ok-detail"}   # app-status: Nextcloud's occ status; ok-detail: the gate's {"ok", "detail"}
U_DUMPS = {"none", "postgres"}
U_ROLLBACK = {"image", "none"}
U_KEYS = {"wait", "version", "site", "health", "major"}
U_OPTIONAL = {"busy", "data_copy"}
U_BUSY = {"none", "check"}
U_DATA_COPY = {"none", "every", "major"}
U_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def update_only(r):
    """True for a format-3 recipe: update rules for an app installed by hand (never installable)."""
    return isinstance(r, dict) and r.get("schema") == UPDATE_ONLY_SCHEMA


def _seconds(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def check_update_block(u):
    """Problems with an update block in the built-in recipes' words (empty = fine): wait, version, site, health, major,
    and optional busy / data_copy. The same rules for a built-in recipe and a format-3 one from a repository."""
    bad = []
    if not isinstance(u, dict) or not U_KEYS <= set(u) <= U_KEYS | U_OPTIONAL:
        return [f"update must have {sorted(U_KEYS)}, and may have {sorted(U_OPTIONAL)}"]
    if u.get("busy", "none") not in U_BUSY:
        bad.append(f"update.busy: one of {sorted(U_BUSY)}")
    if u.get("data_copy", "none") not in U_DATA_COPY:
        bad.append(f"update.data_copy: one of {sorted(U_DATA_COPY)}")
    if not _seconds(u["wait"], 10, 900):
        bad.append("update.wait: 10–900 seconds")
    if u["version"] not in U_VERSION:
        bad.append(f"update.version: one of {sorted(U_VERSION)}")
    s = u["site"]
    if not (isinstance(s, dict) and set(s) <= {"answer_below", "wait", "expect"} and s.get("answer_below") in (300, 400, 500)
            and _seconds(s.get("wait"), 0, 900) and isinstance(s.get("expect", ""), str) and len(s.get("expect", "")) <= 80):
        bad.append("update.site: answer_below 300/400/500, wait 0–900, an optional short 'expect'")
    if u["health"] not in U_HEALTH:
        bad.append(f"update.health: one of {sorted(U_HEALTH)} (others need a newer updater)")
    m = u["major"]
    if not (isinstance(m, dict) and set(m) == {"wait", "dump", "rollback"} and _seconds(m["wait"], 60, 3600)):
        bad.append("update.major: wait 60–3600, dump, rollback")
    else:
        d = m["dump"]
        kind = d if d == "none" else d.get("kind") if isinstance(d, dict) else None
        if kind not in U_DUMPS or (kind == "postgres" and not (isinstance(d, dict) and set(d) == {"kind", "service"}
                                                                and U_NAME.match(str(d.get("service", ""))))):
            bad.append("update.major.dump: none, or {kind: postgres, service: <name>}")
        if m["rollback"] not in U_ROLLBACK:
            bad.append("update.major.rollback: 'image' or 'none'")
    return bad


def check_update_only(r, repo_id=None):
    """Errors for a format-3 recipe (empty = accepted)."""
    e = []
    if not isinstance(r, dict) or r.get("schema") != UPDATE_ONLY_SCHEMA:
        return ["not a format-3 recipe"]
    for k in sorted(set(r) - UPDATE_ONLY_KEYS - UPDATE_ONLY_OPTIONAL, key=str):
        e.append(f"unknown field {str(k)[:40]!r} (format 3 holds update rules only: no compose, gaps or install steps)")
    for k in sorted(UPDATE_ONLY_KEYS - set(r)):
        e.append(f"format 3 needs '{k}'")
    if e:
        return e
    if r["kind"] != "update-only":
        e.append("kind: format 3 is 'update-only'")
    for k in ("id", "name", "summary"):
        if not _str(r.get(k), 300) or not r.get(k):
            e.append(f"'{k}' must be a short text")
    if _str(r.get("id")) and not ID.match(r["id"]):
        e.append("'id' must look like <repository>.<app> (lowercase letters, digits, dashes)")
    elif repo_id and not r["id"].startswith(repo_id + "."):
        e.append(f"id {r['id']} doesn't start with the repository's id '{repo_id}.'")
    if "category" in r and not _str(r["category"], 40):
        e.append("'category' must be a short text")
    if "links" in r and not (isinstance(r["links"], dict) and len(r["links"]) <= 10
                             and all(_str(k, 30) and _str(v, 300) for k, v in r["links"].items())):
        e.append("'links' must map short names to addresses")
    m = r["match"]
    imgs = m.get("images") if isinstance(m, dict) and set(m) == {"images"} else None
    if not (isinstance(imgs, list) and 1 <= len(imgs) <= 3 and all(isinstance(x, str) and IMAGE_NAME.match(x) for x in imgs)
            and len(set(imgs)) == len(imgs)):
        e.append("match: {images: [1 to 3 image names, without tag or digest, in small letters]}")
    e += check_update_block(r["update"])
    if "pictures" in r:
        e += pictures_shape(r["pictures"])
    return e


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
    if t == "secret" and slot.get("source") == "ask":            # the gate takes 8–512 (gate 1.5): refused here first
        if not (isinstance(value, str) and 8 <= len(value) < 200 and not UNSAFE.search(value) and " " not in value.strip()):
            return False
        return slot.get("shape") not in SHAPES or bool(SHAPES[slot["shape"]][0].fullmatch(value))
    if t in ("text", "url", "timezone"):
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


CHARS = "no spaces, line breaks or the characters { } $ `"


def rule(slot):
    """What an answer for this gap must look like, in words: shown when one is refused, instead of the answer."""
    t = slot.get("type")
    if t == "folder":
        return "a full path starting with /, under 300 characters, without '..', no line breaks or the characters { } $ `"
    if t == "port":
        return "a whole number from 1024 to 65535"
    if t == "number":
        return "a whole number"
    if t == "secret" and slot.get("shape") in SHAPES:
        return SHAPES[slot["shape"]][1]
    if t == "secret":
        return f"8 to 199 characters, {CHARS}"
    if t in ("text", "url", "timezone"):
        return f"1 to 199 characters, {CHARS}"
    if t == "choice":
        o = slot.get("options") or []
        return "one of: " + ", ".join(str(x) for x in (o if isinstance(o, list) else list(o)))[:200]
    if t == "toggle":
        return "on or off"
    if t == "networks":
        return "1 to 10 private address ranges, like 10.0.0.0/24"
    if t == "user":
        return "a user number and a group number"
    return "a kind of answer this updater doesn't know"


def refusal(name, slot):
    """The message for a refused answer: the gap, its question and the rule. Never what was typed (a key, maybe)."""
    q = str(slot.get("question", "")).strip()[:120]
    return (f"answer for {name} refused" + (f" (“{q}”)" if q else "") + f": it must be {rule(slot)}. "
            "What was typed isn't shown")


LEFT_OUT = object()                     # a secret whose switch is off: its environment entry isn't written at all


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
            raise Refused(refusal(name, s))     # never the answer itself: it may be a pasted key (0.9.6)
        return v

    for name, s in slots.items():           # plain gaps first; folders under a main folder and toggles after
        if s["type"] == "secret" and not is_asked(slots, s, answers):
            vals[name] = None; continue     # format 2: its switch is off → its environment entry is left out
        if s["type"] == "secret" and s.get("source", "generate") == "generate":
            vals[name] = {"generate": s["length"]} if for_gate else \
                "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(s["length"]))
            continue
        if "under" in s or s["type"] == "toggle":
            continue
        if not is_asked(slots, s, answers):    # a switch that's off, or (0.9.6) an answer of a choice it isn't for
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
            if v is None:
                return LEFT_OUT
            env[key] = v if not for_gate or isinstance(v, dict) else {"value": v}
            return "${" + key + "}"
        return " ".join(SLOT.sub(lambda m: str(vals[m.group(1)][m.group(2)] if m.group(2) else vals[m.group(1)]), text).split()) \
            if SLOT.search(text) else text

    def fill_entry(k, e):
        """A value with gaps inside (0.9.6): each answer written in its way, the whole value to .env as one secret."""
        text = e["value"] if "value" in e else e["cases"][vals[e["by"]]]
        put = {}
        def gap(m):
            put[m.group(1)] = ENCODE[e["inside"]](str(vals[m.group(1)]))
            return put[m.group(1)]
        out = SLOT.sub(gap, text)
        why = value_problem(out)
        if why:
            q = lambda n: f"“{str(slots[n].get('question', n)).strip()[:80]}”"
            if len(out) > VALUE_MAX:
                top = sorted(put, key=lambda n: -len(put[n]))[:2]
                who = "; the longest answers: " + ", ".join(f"{q(n)} ({len(put[n])} characters once written in)" for n in top)
            else:
                odd = [n for n, x in put.items() if not x.isprintable() or x != x.strip() or "#" in x or "$" in x
                       or x[:1] in ("\"", "'", "`")]
                who = ("; check: " + ", ".join(q(n) for n in odd)) if odd else ""
            raise Refused(f"{k} {why}{who}. What was typed isn't shown")
        env[k] = {"value": out} if for_gate else out
        return "${" + k + "}"

    def rebuild(node, at=()):
        if isinstance(node, dict):
            here = len(at) == 3 and at[0] == "services" and at[2] == "environment"
            out = {}
            for k, v in node.items():
                v = fill_entry(k, v) if here and isinstance(v, dict) else rebuild(v, at + (k,))
                if v is not LEFT_OUT:
                    out[k] = v
            return out
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
    said = {}
    for s in slots.values():
        if s["type"] == "secret":
            said.setdefault("a password you choose (kept in .env, never shown)" if s.get("kind") == "password"
                            else "a password or key you paste in (kept in .env, never shown)" if s.get("source") == "ask"
                            else "passwords made for it (kept in .env, never shown)", []).append(s.get("asked_if"))
    for what, ifs in said.items():          # when = "always", a switch's name, or (0.9.6) the choice it depends on
        for a in ifs:
            out.append(("secret", what, "always" if always(slots, a, ifs) else a if isinstance(a, str) else asked_by(a)[0]))
    out = list(dict.fromkeys(out))
    out.append(("outside", "nothing from outside home: making it reachable from outside is a separate step, by hand", "always"))
    return out
