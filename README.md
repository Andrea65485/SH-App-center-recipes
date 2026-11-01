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

## Files

- `repository.yaml` — this repository's id (`sh-app-centre`: every recipe id starts with it) and maintainer.
- `<app>/recipe.yaml`, `<app>/description.md` — one app.
- `index.yaml`, `index.yaml.sig` — made by the maintainer's publish script; never edited by hand.

This repository's signing key: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDrCHFLVrJleMkQfo3PAKEilQu1a8mKHsCxzmANJlFHc`,
fingerprint `SHA256:BWc7rfReJ655yZFGJyataqIjn/5zj0lRaxFJz+ZgXzg`.

## License

MIT (see `LICENSE`): use, change and share freely; it comes with no warranty.
