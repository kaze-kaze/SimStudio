"""Create a source ZIP from a validated sdist, and checksum all release packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

from check_distribution import inspect


def package(directory: Path) -> dict:
    sdists = list(directory.glob("*.tar.gz"))
    wheels = list(directory.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        raise ValueError("Use a release directory containing exactly one sdist and one wheel")
    inspect(sdists[0])
    inspect(wheels[0])
    version = sdists[0].name.removeprefix("text_to_ansys-").removesuffix(".tar.gz")
    target = directory / f"SimStudio-{version}-source.zip"
    with tarfile.open(sdists[0]) as source, zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(source.getmembers(), key=lambda m: m.name):
            if member.isfile():
                with source.extractfile(member) as stream:
                    info = zipfile.ZipInfo(member.name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, stream.read())
    checks = [inspect(path) for path in (*sdists, *wheels, target)]
    assets = sorted([*sdists, *wheels, target])
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in assets}
    (directory / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8", newline="\n",
    )
    return {"status": "PASS", "artifacts": checks, "sha256": hashes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(package(parser.parse_args().directory)))
