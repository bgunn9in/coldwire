#!/usr/bin/env python3
"""Verify the release files and run both extracted launchers on this OS."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from package_release import CHECKSUMS, LIST_FILES, LISTS, PANEL, READMES, SNAPSHOTS, SPA, safe_member


def check_links(root):
    for relative in ("README.md", "README.ru.md", "docs/lists.md", "docs/ru/lists.md",
                     "docs/sources.md", "docs/ru/sources.md", "docs/access-panel.md", "docs/ru/access-panel.md"):
        page = root / relative
        if not page.exists():
            continue
        for link in re.findall(r"\]\(([^)]+)\)", page.read_text(encoding="utf-8")):
            if "://" in link:
                continue
            path, _, anchor = link.partition("#")
            target = (page.parent / path).resolve() if path else page
            if not target.is_relative_to(root) or not target.exists():
                raise ValueError(f"{relative}: broken link {link}")
            if anchor and target.suffix == ".md":
                headings = re.findall(r"^#+ (.+)$", target.read_text(encoding="utf-8"), re.M)
                slugs = {re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-") for title in headings}
                if anchor not in slugs:
                    raise ValueError(f"{relative}: broken link {link}")


def verify(folder):
    checksums = dict(line.split("  ", 1)[::-1] for line in (folder / CHECKSUMS).read_text().splitlines())
    if set(checksums) != {PANEL, LISTS}:
        raise ValueError("Expected checksums for both ZIPs")
    bundled = {}
    for name, launcher in ((PANEL, "COLDWIRE-Admin"), (LISTS, "COLDWIRE-Lists")):
        zip_path = folder / name
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != checksums[name]:
            raise ValueError(f"Checksum mismatch: {name}")
        with TemporaryDirectory(prefix="coldwire release ") as temporary, ZipFile(zip_path) as archive:
            root = Path(temporary).resolve()
            entries = archive.namelist()
            required = set(LIST_FILES) | READMES.keys()
            if name == PANEL:
                required |= {SPA, "docs/access-panel.md", "docs/ru/access-panel.md", "COLDWIRE-Admin.sh", "COLDWIRE-Admin.cmd"}
            if not required.issubset(entries) or (name == LISTS and set(entries) != required):
                raise ValueError(f"Unexpected contents: {name}")
            if len(entries) != len(set(entries)) or not all(safe_member(entry) for entry in entries) or archive.testzip():
                raise ValueError(f"Invalid ZIP: {name}")
            snapshots = {snapshot: archive.read(snapshot) for snapshot in SNAPSHOTS}
            if bundled and snapshots != bundled:
                raise ValueError("The two ZIPs include different snapshots")
            bundled = snapshots
            archive.extractall(root)
            check_links(root)
            command = (["cmd.exe", "/d", "/c", f"{launcher}.cmd"] if os.name == "nt"
                       else ["bash", f"{launcher}.sh"])
            if name == PANEL:
                command.append("update-lists")
            output = root / "offline output"
            subprocess.run([*command, "--offline", "--output", output.name], cwd=root, check=True)
            if {file.name: file.read_bytes() for file in output.iterdir()} != snapshots:
                raise ValueError(f"{launcher} did not reproduce both bundled lists")
            print(f"Verified {name} and {launcher}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    verify(parser.parse_args().folder.resolve())
