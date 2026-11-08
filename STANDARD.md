# The recipe format (draft 0.7: format 2)

A **recipe** describes one self-hosted app so that an updater can install and update it safely, with you. It is **data,
not a script**: everything that is the same for everyone is written out, and every value that depends on *your* home
(a folder, an address, a password) is a **gap**, written `{{name}}`. The updater suggests a value for each gap from the
machines it can see, asks you, and keeps your answers on your own computer — they are never published.

The checker in `tools/` enforces everything below; when this text and the checker disagree, the checker wins (and
this text is wrong — please fix it in your fork).

- [The repository](#the-repository) · [A recipe](#a-recipe) · [Format 2: the Store's facts](#format-2-the-stores-facts) · [Gaps](#gaps) · [The compose part](#the-compose-part) ·
  [Extra access](#extra-access) · [What it can do (worked out, not declared)](#what-it-can-do-worked-out-not-declared) ·
  [Updating](#updating) · [Pictures](#pictures) · [The file itself](#the-file-itself) · [Signing and publishing](#signing-and-publishing) ·
  [Checking your recipe](#checking-your-recipe) · [Not in this version](#not-in-this-version)

## The repository

```
repository.yaml               schema: 1, id, name, maintainer, url — every recipe id starts with "<id>."
index.yaml, index.yaml.sig    made by tools/publish.py, never by hand (see Signing and publishing)
<app>/recipe.yaml             one folder per app; <app> = lowercase letters, digits, dashes
<app>/description.md          optional, plain text (not yet covered by the signature: not shown by updaters yet)
<app>/icon.svg or icon.png    optional: the app's icon (see Pictures)
<app>/screenshots/1–4.webp    optional: up to 4 screenshots, .webp or .png (see Pictures)
examples/<app>/recipe.yaml    examples: checked like recipes, but never listed in the index (not installable)
```

## A recipe

| Field | What it holds | Limits |
|---|---|---|
| `schema` | `2` for a new recipe ([Format 2](#format-2-the-stores-facts)); `1` is the older format, still accepted. A reader that doesn't know a recipe's schema leaves that app out | |
| `id` | `<repository id>.<app>`, the same `<app>` as its folder | lowercase letters, digits, dashes |
| `name`, `summary`, `version` | the store page: what it's called, one line about it, the version written for | short texts |
| `category` | format 2: **required**, one from [the list](#format-2-the-stores-facts) · format 1: optional free text (the Store lists it under *Other*) | format 1: ≤ 40 characters |
| `also`, `licence`, `use_from` | format 2 only: [see below](#format-2-the-stores-facts) | |
| `links` | optional: `home`, `notes` (release notes) | addresses; updaters may show only some sites |
| `needs` | `platforms` (e.g. `[linux/amd64, linux/arm64]`), `memory_mb`, `internet` (format 2: `{level, why}`, [below](#format-2-the-stores-facts); format 1: a plain note), a plain note `https`, and `elevated` ([Extra access](#extra-access)) | |
| `slots` | every gap: its type, its question, its help ([Gaps](#gaps)) | at most 40 |
| `tips` | optional notes shown after installing; may show gaps, never secrets | at most 10 |
| `host_steps` | optional things to do by hand on the machine, shown only when a switch is on | at most 5 |
| `compose` | the fixed part: `services` only, with gaps as `{{name}}` ([The compose part](#the-compose-part)) | 1–10 services |
| `update` | how to update it safely ([Updating](#updating)) | |

**Any other field is refused.** No logic: no conditions, no loops, no commands — apart from the switches described below.

## Format 2: the Store's facts

`schema: 2` adds what a Store needs for its categories and filters. Everything else is the same as format 1.

```yaml
schema: 2
category: documents                    # one from the list below
also: [files]                          # optional: up to 2 more, for an app that belongs in two places
licence: AGPL-3.0-only                 # the app's licence, its SPDX name
use_from: [browser, phone-app]         # how people use it
needs:
  internet: {level: optional, why: "Downloads its OCR languages the first time you pick one."}
```

| Field | Rule |
|---|---|
| `category` | **required**, one of the 15 below |
| `also` | optional: up to 2 more from the same list, not repeating `category` |
| `licence` | **required**: the SPDX name of the **app's** licence (`AGPL-3.0-only`, `MIT`, `CC-BY-NC-SA-4.0`), or `LicenseRef-<name>` for one SPDX doesn't list. Read it in the app's own repository. Stores show it **as declared** by the recipe, never as checked |
| `use_from` | **required**: 1–4 of `browser`, `desktop-app` (an app on a computer), `phone-app`, `devices` (other devices and apps talk to it; no page of its own, like an MQTT broker) |
| `needs.internet` | **required**: `level` is `none` (works with no internet at all), `optional` (some features use it) or `needed` (it doesn't work without). `why`: what it uses the internet for, in plain words (required unless `none`) |

**Categories** (the Store's words beside each): `media` Films, TV and audiobooks · `music` Music · `photos` Photos ·
`games` Games · `reading` News, bookmarks and books · `documents` Documents and PDFs · `files` Files, sync and backups ·
`smart-home` Smart home · `household` Household · `network` Network and remote access · `security` Passwords and
logins · `monitoring` Monitoring and alerts · `development` Code · `automation` Automation · `tools` Small tools.

**Worked out, never written** (the same code in every reader): whether it runs on arm64 (from `platforms`), whether it
needs **a key of yours** (a pasted `secret`: *needed*; only behind a switch: *optional*; for now this counts a password
you choose yourself too: see [Not in this version](#not-in-this-version)), whether it reads a folder of
yours, whether it has extra access, and whether its licence is an **open-source** one. Open source = one of these
OSI-approved names: AGPL-3.0, GPL-2.0, GPL-3.0, LGPL-2.1, LGPL-3.0 (each `-only` or `-or-later`), MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, MPL-2.0, ISC, EPL-2.0, EUPL-1.2, Unlicense, 0BSD, Zlib. Anything else (`CC-BY-NC-SA-4.0`,
`BUSL-1.1`, `LicenseRef-…`) is shown as *not an open-source licence*.

**A key you paste in can be optional** (format 2 only): a `secret` with `source: ask` and `asked_if: <switch>` is asked
only while that switch is on, and may be used directly as a whole environment value. While the switch is **off**, its
environment line isn't written at all, nor its line in `.env`. Example: game covers from an online database, with your
own free keys, behind a switch that starts off.

**Readers:** the Homelab updater from 0.9.5 and store-watch from 1.2 read format 2. Older ones leave a format-2 recipe
out (*"signed, but this checker doesn't accept it (a newer format?)"*) and show the rest of the repository.

## Gaps

Every gap is declared under `slots`, by a name of lowercase letters, digits and `_`. An undeclared `{{x}}` anywhere is
refused.

**Written for someone new to self-hosting.** Every gap has a **`question`** (what you're deciding, in everyday words —
aim for ≤ 70 characters) and a **`help`** (one or two sentences: why it's asked and what happens — aim for ≤ 260). Say
what it's *for*: "The address you'll open it at, at home", not "Web port". The checker warns about technical words in
questions (port, volume, container, uid…).

| Type | The updater suggests (`suggest:`) | An answer is accepted when |
|---|---|---|
| `folder` | `app-folder`: made for the app, where your other apps keep their data · `yours`: a folder you already have (your music), only read — see below | an absolute path; no `..`, line breaks, `{`, `}`, `$` or backticks |
| `port` | `free-port`: the `default` if free there, else the next free one | a whole number 1024–65535 |
| `secret` | — `source: generate` (+ `length` 16–128): made on the machine at install, **never shown** — for what nobody types (a database password, an encryption key) · `source: ask`: you type or paste it in (a password you'll sign in with, a sign-in key) | goes to the project's `.env` only, as `${NAME}`; an `ask` answer has 8–199 characters, no spaces, `{`, `}`, `$` or backticks |
| `timezone`, `user` | `host`: read from the machine; shown, not asked (`user` has `.uid` and `.gid`) | |
| `url` | `your-domain` (+ `prefix`), `lan-address` | one line, no spaces |
| `choice` | — `options`: a list, or labels → values (`"English (UK) — Alan": en_GB-alan-medium`); `default` is one of them | one of the options |
| `toggle` | — a switch: `default` true/false, and fixed `on` and `off` values | true or false |
| `networks` | `home-network`: your home's address range | private address ranges only (`0.0.0.0/0` is refused) |
| `number` | — | a whole number |
| `text` | — | one line, no spaces, no `{`, `}`, `$` or backticks |

More:
- **A password you'll sign in with is `source: ask`.** A generated secret is never shown, not even once after
  installing, so an admin password made that way couldn't be used.
- **`advanced: true`** puts a gap under *More options*; its suggestion is used unless you open it.
- **Every folder gap says which kind it is:** `suggest: app-folder` or `suggest: yours` (or `under:` a main folder).
- **A folder of yours** (`suggest: yours`): a library you already keep, such as your music. The app only **reads** it:
  - mount it whole and read only, `"{{music}}:/music:ro"` — no sub-path, never `:rw`, and only as a volume (not in
    `environment` or `command`);
  - no `default`, `sub`, `advanced` or `asked_if`, and nothing `under` it: it's always asked, and never made or written;
  - at most 3 per app;
  - **you approve it on the machine** before installing (the updater shows the exact line:
    `sudo /usr/local/sbin/updater-gate-accept --folder <folder> <app>`). The machine refuses a root, a Team folder's or
    your personal folder's top, another app's folders, a folder holding a hidden folder (`.ssh`) at its top, links, and
    names with spaces. Anything inside the approved folder can change freely; the folder itself must stay the same one.
  - **Read only isn't private:** the app can read everything there, and every app can reach the internet. Ask for the
    narrowest folder that works (`Music`, not your whole personal folder).
- **One folder question, not four:** a folder gap with `under: <main folder gap>` and `sub: <name>` is made inside the
  main folder. Only the main folder is asked.
- **Switches** (`toggle`): you only flip them; the recipe fixes what *on* and *off* mean
  (`on: "--advertise-exit-node"`, `off: ""`). Optional settings always start **off**. An `on`/`off` value may contain
  other plain gaps, never a secret or another switch.
- **`asked_if: <switch>`:** the gap is asked only while that switch is on — and may be used **only inside that switch's
  `on` value**, never directly in the compose part (a gap that wasn't asked has no value). The one exception, in format
  2: a secret you paste in ([above](#format-2-the-stores-facts)), whose line is left out while the switch is off.
- **`host_steps`** (`if_on: [switches]`, `text`): changes outside the app a setting needs (turning on IP forwarding…).
  The updater shows them; it never does them.

## The compose part

`compose:` holds `services:` only, written like a Docker Compose file. Each service may have exactly these keys:

| Key | Rule |
|---|---|
| `image` | a name and a tag (`rhasspy/wyoming-piper:2.5.2`); the updater pins the digest when it installs |
| `ports` | `"{{a port gap}}:<inside port>"` — the outside port is always a port gap; none on the host network |
| `volumes` | `"{{a folder gap}}[/sub/path]:<inside path>[:ro|:rw]"` — the outside path is always a folder gap: no fixed host paths, never the Docker socket. A folder of yours: `"{{gap}}:<inside path>:ro"` exactly |
| `environment` | NAMES → plain values; a secret only as a **whole** value (`DB_PASSWORD: "{{db_pass}}"`) |
| `command` | a text or a list of texts |
| `depends_on` | other services of the same recipe |
| `user` | only `"{{<a user gap>.uid}}:{{<a user gap>.gid}}"`: the app runs as your own account instead of root. Never a fixed number, never `0` or `root`. **Use it wherever the image allows**: the app's folders are then made for that account. An image that switches accounts by itself (`PUID`/`PGID`) starts as root and finds folders it can't write to (*operation not permitted*, restarting) |
| `restart`, `healthcheck` | plain values |
| `deploy` | `resources` only |

Plus, only when declared under `needs.elevated`: `network_mode: host`, `cap_add: [NET_ADMIN]`, `cap_add: [NET_RAW]`,
`devices: [/dev/net/tun:/dev/net/tun]`. **One database per app:** an app that needs one brings its own.

**Listen on `0.0.0.0`, not `::`.** Some machines give containers no IPv6, and an app that listens only on `::` then
stops at start (*address not available*, restarting). Where the app has a setting for it, set it to `0.0.0.0` (n8n:
`N8N_LISTEN_ADDRESS`, linkding: `LD_SERVER_HOST`). The port is reached over IPv4 anyway.

**PostgreSQL 18 and later keep their data one level up:** mount the database's folder at `/var/lib/postgresql`. 17 and
older use `/var/lib/postgresql/data`. A volume at the old place on 18 is ignored, and the database is lost on the next
restart. Moving a recipe from 17 to 18 is therefore a major update (a dump first), never just a new tag.

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
recipe itself**: its volumes (*its own folder* when the gap is `suggest: app-folder` or inside one, read and change or
read only; *reads a folder you choose — read only; it can't change it. You approve it on the machine first* for
`suggest: yours`), its ports or host network, the
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

## Pictures

An icon and up to 4 screenshots, named in the recipe, each with **where it comes from**:
```yaml
pictures:
  icon: {file: icon.svg, source: project, from: "https://github.com/<project>/…/logo.svg", licence: "MIT, © <project>"}
  screenshots:
    - {file: screenshots/1.webp, source: install, caption: "Your library, freshly installed"}
```
| | Rule |
|---|---|
| `source` | `install` — taken by you on a **fresh install** (show nothing of yours: no names, addresses or files) · `project` — from the app's own site or repository, with `from` (an https address) and its `licence` · `mockup` — drawn to show the app: always labelled **Mockup** where it's shown |
| Icon | `icon.svg` held to plain shapes (no scripts, no `on…` attributes, no images, links or styles that fetch anything) or `icon.png`, square, 128–512 px; at most 32 KiB |
| Screenshots | `screenshots/1.webp` … `4.webp` (or `.png`), 640×360 to 1920×1200, at most 400 KiB each, checked by their real header |
| Caption | each screenshot's, at most 120 characters of plain text — also what screen readers say |

- **Signed like the recipe:** `publish.py` lists each picture in `index.yaml` with its SHA-256 and size. A picture
  whose bytes differ refuses the whole repository; one that breaks the rules above is only left out.
- **Look at each new picture yourself:** `publish.py` asks once per new picture whether it shows anything of yours.
  No word list can look inside a picture.
- **A picture from the project keeps its own licence**, named in the recipe; this repository's licence doesn't cover it.
- **Updaters before 0.9.3 and store-watch before 1.1 refuse an index with pictures**: publish them with `--pictures`
  once yours are updated.

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

Start from `TEMPLATE.yaml` (format 2). The examples (still format 1) show more: `examples/paperless-ngx` (three containers, its own database, one
main folder with four inside, a generated password), `examples/vaultwarden` (a password server: HTTPS, admin page off),
`examples/mealie` (one container, SQLite), `examples/tailscale` (switches, a question behind a switch, a key you paste
in, declared extra access, a step by hand). `piper/` is a real, published one.

## Not in this version

- **Writing into a folder of yours** (apps that save covers or tags next to your files): read only, always.
- **Folder names with spaces** for a folder of yours (`My Music`): rename it first.
- **Folders on other machines** (network shares) as a folder of yours.
- **A secret inside a longer value** (`postgres://user:{{pass}}@db/app`): a secret can only be a whole value. Use the
  app's separate setting for the password when it has one (for PostgreSQL clients, `PGPASSWORD`).
- **Ports below 1024** (DNS's 53, a web server's 80) and **kernel settings** (`sysctls`, as VPNs use).
- **Images outside Docker Hub and GitHub's registry** (codeberg.org, quay.io, lscr.io), and **tags with letters or
  hashes** (`2024.10.22-7ca5933`): they install, but the dashboard can't follow their updates yet.
- A settings **file** that contains secrets (some apps keep their tokens in a JSON or YAML file, not in environment
  variables) — such apps can't be written yet.
- Optional containers (an extra service when a switch is on).
- Descriptions covered by the signature (so updaters can show them).
- **Telling a password you choose apart from a key from another service** (planned: `kind: password` on such a secret).
  Until then, *No key of yours needed* also hides an app that only asks you to choose a sign-in password.
