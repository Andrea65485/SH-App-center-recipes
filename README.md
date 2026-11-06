# SH App centre recipes

**A proof of concept.** This repository shows how a small, personal "app centre" for self-hosted apps can work:
recipes as plain data, a signed index, and an updater that checks everything before it touches a machine. The recipes
here are real and maintained for one home, and they double as examples.

**Want to use it? Fork it, and run your own.** There is no support and no promise that a recipe here will keep up with
your setup or with new versions. Your fork gets **its own signing key and its own repository id**; your updater pins
your key, not this one. Please don't point an updater at this repository and rely on it.

## How it works

- **A recipe is data, not a script.** `<app>/recipe.yaml` says which containers an app needs, which folders, addresses
  and settings it asks for (as *gaps* the updater fills in with you, with suggestions), and how to update it safely.
  It can't run commands, can't ask for more access than it declares (and some access, such as `privileged` or the
  Docker socket, can never be granted), and never makes anything reachable from the internet.
- **What an app gets is worked out from the recipe itself** (its folders, its addresses, any declared extra access),
  never from text its author wrote — so a recipe can't describe itself as harmless.
- **The index is signed.** `index.yaml` lists every recipe with its SHA-256 and size, a serial number and an expiry
  date; `index.yaml.sig` is an SSH signature (`ssh-keygen -Y sign`) by the maintainer's key, which never leaves the
  maintainer's machine. An updater checks it against the one key it pinned when the repository was added, and refuses
  an index signed by anything else, an older serial than one it has already seen (a replayed old index), an expired
  index (publishing stopped, or an old copy), and any recipe whose bytes differ from what the index names. Someone
  who took over the GitHub account still couldn't publish a recipe an updater would accept.
- Versions are pinned by digest at install time; the tag in a recipe is the version it was written and tested for.

## Write your own recipes

1. Read **[STANDARD.md](STANDARD.md)**, the format, with every rule the checker enforces.
2. Copy **[TEMPLATE.yaml](TEMPLATE.yaml)** to `<app>/recipe.yaml`; the comments say what to change.
3. Look at **[examples/](examples/)** for more: a database and a generated password (`paperless-ngx`), HTTPS and an
   admin page kept off (`vaultwarden`), the simplest case (`mealie`), switches, a question behind a switch, a key you
   paste in and declared extra access (`tailscale`). `piper/` and `stirling-pdf/` are real, published ones.
4. Check it: `python3 tools/check.py <app>/recipe.yaml --permissions` (Python 3.11+ and PyYAML). Then check the whole
   repository: `python3 tools/check.py .`
5. In your fork, sign and publish with your own key: `python3 tools/publish.py . --key ~/.ssh/<your-id>-signing`
   (see STANDARD.md, *Signing and publishing*).

## Files

- `repository.yaml` — this repository's id (`sh-app-centre`: every recipe id starts with it) and maintainer.
- `<app>/recipe.yaml`, `<app>/description.md` — one app.
- `examples/` — examples of the format: checked, but never in the index (not installable).
- `tools/` — the checker and the publish script (the updater's own checking code, copied).
- `index.yaml`, `index.yaml.sig` — made by the maintainer's publish script; never edited by hand.

This repository's signing key: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDrCHFLVrJleMkQfo3PAKEilQu1a8mKHsCxzmANJlFHc`,
fingerprint `SHA256:BWc7rfReJ655yZFGJyataqIjn/5zj0lRaxFJz+ZgXzg`.

## License

MIT (see `LICENSE`): use, change and share freely; it comes with no warranty.

**Except pictures from the projects themselves:** an icon or screenshot whose recipe says `source: project` keeps its
project's own licence, named in that recipe (e.g. GameVault's icon: CC BY-NC-SA 4.0, © Phalcode). Pictures with
`source: install` or `mockup` were made by this repository's maintainer and are covered by the MIT licence.
