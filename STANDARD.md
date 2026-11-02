# The recipe format (draft 0.6)

A **recipe** describes one self-hosted app so that an updater can install and update it safely, with you. It is **data,
not a script**: everything that is the same for everyone is written out, and every value that depends on *your* home
(a folder, an address, a password) is a **gap**, written `{{name}}`. The updater suggests a value for each gap from the
machines it can see, asks you, and keeps your answers on your own computer — they are never published.

The checker in `tools/` enforces everything below; when this text and the checker disagree, the checker wins (and
this text is wrong — please fix it in your fork).

- [The repository](#the-repository) · [A recipe](#a-recipe) · [Gaps](#gaps) · [The compose part](#the-compose-part) ·
  [Extra access](#extra-access) · [What it can do (worked out, not declared)](#what-it-can-do-worked-out-not-declared) ·
  [Updating](#updating) · [The file itself](#the-file-itself) · [Signing and publishing](#signing-and-publishing) ·
  [Checking your recipe](#checking-your-recipe) · [Not in this version](#not-in-this-version)

## The repository

```
repository.yaml               schema: 1, id, name, maintainer, url — every recipe id starts with "<id>."
index.yaml, index.yaml.sig    made by tools/publish.py, never by hand (see Signing and publishing)
<app>/recipe.yaml             one folder per app; <app> = lowercase letters, digits, dashes
<app>/description.md          optional, plain text (not yet covered by the signature: not shown by updaters yet)
examples/<app>/recipe.yaml    examples: checked like recipes, but never listed in the index (not installable)
```

## A recipe

| Field | What it holds | Limits |
|---|---|---|
| `schema` | always `1`; an updater refuses a schema it doesn't know | |
| `id` | `<repository id>.<app>`, the same `<app>` as its folder | lowercase letters, digits, dashes |
| `name`, `summary`, `version` | the store page: what it's called, one line about it, the version written for | short texts |
| `category` | optional, one word or two | ≤ 40 characters |
| `links` | optional: `home`, `notes` (release notes) | addresses; updaters may show only some sites |
| `needs` | `platforms` (e.g. `[linux/amd64, linux/arm64]`), `memory_mb`, plain notes `internet` and `https`, and `elevated` ([Extra access](#extra-access)) | |
| `slots` | every gap: its type, its question, its help ([Gaps](#gaps)) | at most 40 |
| `tips` | optional notes shown after installing; may show gaps, never secrets | at most 10 |
| `host_steps` | optional things to do by hand on the machine, shown only when a switch is on | at most 5 |
| `compose` | the fixed part: `services` only, with gaps as `{{name}}` ([The compose part](#the-compose-part)) | 1–10 services |
| `update` | how to update it safely ([Updating](#updating)) | |

**Any other field is refused.** No logic: no conditions, no loops, no commands — apart from the switches described below.

## Gaps

Every gap is declared under `slots`, by a name of lowercase letters, digits and `_`. An undeclared `{{x}}` anywhere is
refused.

**Written for someone new to self-hosting.** Every gap has a **`question`** (what you're deciding, in everyday words —
aim for ≤ 70 characters) and a **`help`** (one or two sentences: why it's asked and what happens — aim for ≤ 260). Say
what it's *for*: "The address you'll open it at, at home", not "Web port". The checker warns about technical words in
questions (port, volume, container, uid…).

| Type | The updater suggests (`suggest:`) | An answer is accepted when |
|---|---|---|
| `folder` | `app-folder`: where your other apps keep their data, plus `sub` | an absolute path; no `..`, line breaks, `{`, `}`, `$` or backticks |
| `port` | `free-port`: the `default` if free there, else the next free one | a whole number 1024–65535 |
| `secret` | — `source: generate` (+ `length` 16–128): made by the updater · `source: ask`: you paste it in (a sign-in key) | goes to the project's `.env` only, as `${NAME}` |
| `timezone`, `user` | `host`: read from the machine; shown, not asked (`user` has `.uid` and `.gid`) | |
| `url` | `your-domain` (+ `prefix`), `lan-address` | one line, no spaces |
| `choice` | — `options`: a list, or labels → values (`"English (UK) — Alan": en_GB-alan-medium`); `default` is one of them | one of the options |
| `toggle` | — a switch: `default` true/false, and fixed `on` and `off` values | true or false |
| `networks` | `home-network`: your home's address range | private address ranges only (`0.0.0.0/0` is refused) |
| `number` | — | a whole number |
| `text` | — | one line, no spaces, no `{`, `}`, `$` or backticks |

More:
- **`advanced: true`** puts a gap under *More options*; its suggestion is used unless you open it.
- **One folder question, not four:** a folder gap with `under: <main folder gap>` and `sub: <name>` is made inside the
  main folder. Only the main folder is asked.
- **Switches** (`toggle`): you only flip them; the recipe fixes what *on* and *off* mean
  (`on: "--advertise-exit-node"`, `off: ""`). Optional settings always start **off**. An `on`/`off` value may contain
  other plain gaps, never a secret or another switch.
- **`asked_if: <switch>`:** the gap is asked only while that switch is on — and may be used **only inside that switch's
  `on` value**, never directly in the compose part (a gap that wasn't asked has no value).
- **`host_steps`** (`if_on: [switches]`, `text`): changes outside the app a setting needs (turning on IP forwarding…).
  The updater shows them; it never does them.

## The compose part

`compose:` holds `services:` only, written like a Docker Compose file. Each service may have exactly these keys:

| Key | Rule |
|---|---|
| `image` | a name and a tag (`rhasspy/wyoming-piper:2.5.2`); the updater pins the digest when it installs |
| `ports` | `"{{a port gap}}:<inside port>"` — the outside port is always a port gap; none on the host network |
| `volumes` | `"{{a folder gap}}[/sub/path]:<inside path>[:ro|:rw]"` — the outside path is always a folder gap: no fixed host paths, never the Docker socket |
| `environment` | NAMES → plain values; a secret only as a **whole** value (`DB_PASSWORD: "{{db_pass}}"`) |
| `command` | a text or a list of texts |
| `depends_on` | other services of the same recipe |
| `user` | only `"{{<a user gap>.uid}}:{{<a user gap>.gid}}"`: the app runs as your own account instead of root. Never a fixed number, never `0` or `root` |
| `restart`, `healthcheck` | plain values |
| `deploy` | `resources` only |

Plus, only when declared under `needs.elevated`: `network_mode: host`, `cap_add: [NET_ADMIN]`, `cap_add: [NET_RAW]`,
`devices: [/dev/net/tun:/dev/net/tun]`. **One database per app:** an app that needs one brings its own.

## Extra access

Most apps get their own folder and an address or two. A few (a VPN, a network tool) need more. The recipe must
**declare each item with a reason in plain words** (at least 20 characters) under `needs.elevated`; store pages show it
in red with that reason. Only these four can ever be granted:

| Item | In the compose part | Shown as |
|---|---|---|
| `host-network` | `network_mode: host` | joins the home network directly |
| `net-admin` | `cap_add: NET_ADMIN` | may change network settings |
| `net-raw` | `cap_add: NET_RAW` | may send raw test messages |
| `tun-device` | `devices: /dev/net/tun:/dev/net/tun` | a virtual network card |

**Never, whatever a recipe says:** `privileged`, any other capability (`SYS_ADMIN`…), other devices, `pid`, `ipc`,
`security_opt`, the Docker socket, fixed host paths. Making an app reachable from the internet is **never** part of an
install.

## What it can do (worked out, not declared)

The list of what an app gets — shown on its store page, before installing, and afterwards — is **worked out from the
recipe itself**: its volumes (*its own folder* when the gap is `suggest: app-folder` or inside one; otherwise *a folder
you choose*, such as your music — each read and change, or read only with `:ro`), its ports or host network, the
internet (every app can reach it), whether it runs as your own account (`user`), declared extra access, secrets, and
what each switch would add. A recipe can't describe
itself as harmless: its author supplies only the *reasons* beside extra access and the plain notes in `needs`.

## Updating

```yaml
update:
  main: <the service whose image carries the version>
  tags: '^\d+\.\d+\.\d+$'          # which tags are versions of this app (a regular expression)
  health: {check: container-health, service: <service>, wait: 300}
  major: {one_at_a_time: true, dump: {kind: none}, rollback: image}
```

- **`tags`** describes **every** version tag of the app (`'^\d+\.\d+\.\d+$'`), not just the current series: a pattern
  like `'^0\.64\.\d+$'` would never offer 0.65. The updater decides which step is safe (one major at a time). It must
  match the main image's own tag, and may not use repeated groups, back-references or look-arounds (they can make
  matching take practically forever; tag patterns never need them).
- **`health.check`**, how the updater knows the new version works: `http-status` (the page answers below
  `answer_below`, at `path`), `container-health` (the image's own health check), `running-digest` (the new image
  runs), `app-status` and `ok-detail` (a check the updater's machine helper knows for that app). Optional: `service`,
  `path`, `answer_below` (200–599), `wait` (seconds, ≤ 3600).
- **`major.dump`** before a new major version: `none`, `postgres` or `mariadb` (+ `service`: the database service),
  `stop-and-copy` (+ `folder`: a folder gap — stopped, copied, compared, started again).
- **`major.rollback`** after a major has started: `image` (back to the old image is safe) or `none` (the app changes its
  data on start: Roll back is switched off; the way back is the dump). An app that migrates its database on start is
  `none`.

## The file itself

At most 64 KiB, UTF-8 text. **No YAML aliases** (`&a` / `*a`: a tiny file could expand without limit) and no YAML tags
(`!!python/…`). Every field has a fixed type and size (above); a recipe that breaks any rule is refused as a whole,
with every reason listed — never "mostly used".

## Signing and publishing

- `tools/publish.py` checks every recipe (and every example), scans every file for things that look like secrets
  (and, with `--private-words FILE`, for your own home's details — keep that file **outside** the repository: it lists
  what it looks for), writes `index.yaml` — each recipe's SHA-256 and size, a **serial** (the time) and an **expiry**
  (30 days by default, at most 90) — and signs it with `ssh-keygen -Y sign`.
- Updaters trust a repository through **one pinned key**, compared by its fingerprint when the repository is added.
  They refuse an index not signed by it, a serial lower than one they have already seen (an old index replayed), an
  expired index (publishing stopped — publish again at least monthly), and any recipe whose bytes differ from the
  index. Someone who took over the GitHub account still couldn't publish a recipe they'd accept.
- **Forking?** Change `id` in `repository.yaml` (and every recipe id), make your own key
  (`ssh-keygen -t ed25519 -f ~/.ssh/<your-id>-signing`, with a passphrase), and publish with
  `python3 tools/publish.py . --key ~/.ssh/<your-id>-signing --expect-key ~/.ssh/<your-id>-signing.pub`.

## Checking your recipe

Needs Python 3.11+ and PyYAML (`pip install pyyaml`, or your system's `python3-yaml`):

```
python3 tools/check.py .                                   every recipe and example in the repository
python3 tools/check.py <app>/recipe.yaml --permissions     what the app would get, worked out from the recipe
python3 tools/check.py <app>/recipe.yaml --fill answers.yaml   fill it in as a test: the compose file, the .env (masked), the tips
```

Start from `TEMPLATE.yaml`. The examples show more: `examples/paperless-ngx` (three containers, its own database, one
main folder with four inside, a generated password), `examples/vaultwarden` (a password server: HTTPS, admin page off),
`examples/mealie` (one container, SQLite), `examples/tailscale` (switches, a question behind a switch, a key you paste
in, declared extra access, a step by hand). `piper/` is a real, published one.

## Not in this version

- A settings **file** that contains secrets (some apps keep their tokens in a JSON or YAML file, not in environment
  variables) — such apps can't be written yet.
- Optional containers (an extra service when a switch is on).
- Descriptions and pictures covered by the signature (so updaters can show them).
