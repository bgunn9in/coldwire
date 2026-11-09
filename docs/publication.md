# Preparing source for publication

English | [Русский](ru/publication.md)

COLDWIRE was published from a verified source tree with new Git history.
The previous private repository and its objects were not transferred. MIT covers original scripts, tests, documentation and branding.
Third-party software and address-data terms are described in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Distribute only the source tree and public binary bundles under `dist/`.
Exclude `private/`, `generated/`, `.venv/`, profiles, keys, logs, VM disks and
backups. Supply your deployment addresses as command options rather than
embedding them in defaults/examples. Deployment reports, SSH fingerprints,
profiles and backups are private operational data.

## Files and history need separate checks

A normal commit deleting an address does not erase earlier commits. If a
previous history contained deployment details, start from a separate clean
tree with one reviewed initial commit. Do not publish old history, branches,
tags or the working checkout's `.git`. This does not delete copies already
held by other people.

After reviewing content, archive the current tree only:

```bash
git archive --format=zip --output=../coldwire-source.zip HEAD
```

The archive has no `.git`, but **review its contents anyway**: `git archive`
includes committed files even if a later `.gitignore` rule matches them.
For a separate repository, extract the reviewed archive to a new empty directory:

```bash
git init -b main
git add .
git commit -m "Initial source release"
```

Do not copy old `.git` or add old refs. Creating a remote, granting colleagues
access and changing visibility are distinct operations. A local clean copy
does not clean the original GitHub repository's storage.

After rewriting published history, replace old clones rather than merging
them back. GitHub can retain old objects accessible by SHA in cached views;
force-push does not guarantee physical removal. See [GitHub's guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## Release checks

From the repository root:

```bash
python -m pip install -r requirements-deploy.txt
python -m unittest discover -s tests -v
```

SSH host-key tests require Paramiko; without it, that test is skipped. Check
Bash syntax for `servers/*.sh`, local Markdown links, list hashes/counts and
offline reproduction of both JSON files. Review source and nested archives
for real credentials, node addresses and personal local paths. Synthetic
unit-test keys must not match issued credentials.

Preserve licenses and corresponding source in
`dist/awg-native-linux-amd64.tar.gz` and `dist/xray-native-linux-amd64.tar.gz`.
Xray's bundle includes its license and a manifest pointing to the pinned
source version. The project's MIT license does not replace upstream licenses.

Supported server releases are Ubuntu 22.04, 24.04 and 26.04 LTS amd64.
The [LTS report](validation-lts.md), [Ubuntu 22.04 three-mode report](validation-protocols.md)
and [earlier AWG report](validation-native.md) record the tests performed.
A later documentation edit does not imply that the full VM cycle was rerun.

## Initial public release

At the initial release, runtime scripts, tests, address data, binary bundles
and both JSON files were copied unchanged from the verified archive. That edition added branding, MIT
and English documentation while retaining internal identifiers. All 44/44
unit tests and offline list reproduction passed again. Commands, checksums,
language navigation and local links were checked for all 13 RU/EN document
pairs. The SVG header was rendered and visually inspected; its embedded logo
matches the original PNG. The tree and nested archives were checked for
operational credentials, node addresses and personal paths before publishing
the new history.

The full VM cycle was not rerun for these editorial changes: its results
apply to the unchanged scripts documented in the [protocol report](validation-protocols.md).

## English default and additional LTS releases

The main documentation paths are `README.md` and `docs/`. Russian translations
are in `README.ru.md` and `docs/ru/`, with language links on each page.
That update preserved commands and diagrams from the original 13 language
pairs and added a fourteenth pair with the [LTS results](validation-lts.md).
Binary bundles, address data, the PNG logo and both RU JSON files were
unchanged. The SVG header received a new platform caption. Links, hashes and absence of private
data were checked. All 47 unit tests passed on Windows and guest Python
3.12/3.14. Support for the new OS releases was verified in the six VM cycles
listed in the LTS report.

On 10 November, a separate [ordinary-reboot follow-up](validation-lts.md#ordinary-reboots)
added six fresh VM cycles and 24 guest reboots with a locally patched QEMU/WHPX
test build. VPN scripts and released bundles remained unchanged.

The later prose review retained English as the default and the Russian
translations. The README header and topology use matching English and Russian
SVGs. Scripts, commands, address data, binary bundles and both RU JSON files
were unchanged; the VM cycle was not rerun for these documentation changes.
