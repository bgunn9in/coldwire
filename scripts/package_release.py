#!/usr/bin/env python3
"""Build both release ZIPs from the current Git commit."""

import argparse
import hashlib
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
PANEL = "COLDWIRE-Access-Panel.zip"
LISTS = "COLDWIRE-RU-Lists.zip"
CHECKSUMS = "SHA256SUMS.txt"
SPA = "dist/coldwire-spa-linux-amd64"
SNAPSHOTS = ("ru-direct.amnezia.json", "ru-services.amnezia.json")
LIST_FILES = (
    "COLDWIRE-Lists.cmd", "COLDWIRE-Lists.sh", "update_lists.py", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "data/ru-networks.txt", "data/protected-vpn-networks.txt", "data/service-roots.txt", "data/service-addresses.txt",
    "data/verified-cdn-ipv4.json",
    "docs/lists.md", "docs/ru/lists.md", "docs/sources.md", "docs/ru/sources.md", *SNAPSHOTS,
)
READMES = {
    "README.md": """# COLDWIRE RU Lists

[Русский](README.ru.md)

Install Python 3.10 or newer. On Windows, open `COLDWIRE-Lists.cmd`. On Linux, run `bash COLDWIRE-Lists.sh` in this folder.

[Generate and import the lists](docs/lists.md) · [Linux test results](docs/lists.md#linux-test-results)
""",
    "README.ru.md": """# COLDWIRE RU Lists

[English](README.md)

Установите Python 3.10 или новее. На Windows откройте `COLDWIRE-Lists.cmd`. На Linux выполните `bash COLDWIRE-Lists.sh` в этой папке.

[Обновление и импорт списков](docs/ru/lists.md) · [Результаты проверки на Linux](docs/ru/lists.md#результаты-проверки-на-linux)
""",
}


def safe_member(name):
    path = PurePosixPath(name)
    return (not path.is_absolute()
            and not {"..", ".git", ".venv", "private", "generated", "cache"}.intersection(path.parts)
            and "\\" not in name
            and path.suffix not in {".vpn", ".key", ".pem", ".log", ".etl", ".pcap", ".pcapng", ".cwbackup", ".cwkey"})


def standalone_document(path, data, commit):
    included = set(LIST_FILES) | READMES.keys()

    def resolve(match):
        link = match[0]
        if "://" in link or link.startswith("#"):
            return link
        filename, separator, anchor = link.partition("#")
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), filename))
        if target in included or any(member.startswith(target + "/") for member in included):
            return link
        kind = "tree" if filename.endswith("/") else "blob"
        return f"https://github.com/bgunn9in/coldwire/{kind}/{commit}/{target}{separator}{anchor}"

    return re.sub(r"(?<=\]\()([^\)]+)(?=\))", resolve, data.decode("utf-8")).encode("utf-8")


def build(output):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "archive", "--format=zip", commit], cwd=ROOT)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as temp, ZipFile(BytesIO(source)) as tracked:
        if not all(safe_member(name) for name in tracked.namelist()):
            raise ValueError("Git archive includes a private file or an unsafe path")
        work = Path(temp)
        tracked.extractall(work)
        native = tracked.read("dist/awg-native-linux-amd64.tar.gz")
        expected = tracked.read("dist/awg-native-linux-amd64.sha256").decode().split()[0]
        if hashlib.sha256(native).hexdigest() != expected:
            raise ValueError("Native AmneziaWG bundle does not match its checksum")
        go_module = work / "servers/spa"
        env = dict(os.environ, GOTOOLCHAIN="local", CGO_ENABLED="0")
        subprocess.run(["go", "test", "./..."], cwd=go_module, env=env, check=True)
        binary = work / SPA
        subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "-ldflags", "-s -w", "-o", str(binary), "."],
                       cwd=go_module, env=env | {"GOOS": "linux", "GOARCH": "amd64"}, check=True)

        panel = work / PANEL
        panel.write_bytes(source)
        timestamp = tracked.infolist()[0].date_time
        entry = ZipInfo(SPA, timestamp)
        entry.create_system = 3
        entry.external_attr = 0o100755 << 16
        with ZipFile(panel, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr(entry, binary.read_bytes())

        with ZipFile(work / LISTS, "w", compression=ZIP_DEFLATED) as archive:
            for path in LIST_FILES:
                data = tracked.read(path)
                if path.endswith(".cmd"):
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if path.endswith(".md"):
                    data = standalone_document(path, data, commit)
                archive.writestr(tracked.getinfo(path), data, compress_type=ZIP_DEFLATED)
            for path, contents in READMES.items():
                entry = ZipInfo(path, timestamp)
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, contents.encode("utf-8"), compress_type=ZIP_DEFLATED)

        checksums = [f"{hashlib.sha256((work / name).read_bytes()).hexdigest()}  {name}\n" for name in (PANEL, LISTS)]
        (work / CHECKSUMS).write_bytes("".join(checksums).encode("ascii"))
        for name in (PANEL, LISTS, CHECKSUMS):
            (work / name).replace(output / name)
    print(f"Built {PANEL} and {LISTS} from {commit}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output.resolve())
