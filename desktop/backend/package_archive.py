"""Create or safely unpack a complete desktop package using the bundled Python."""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import tarfile


def unpack(source, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Extract the application into an empty folder.")
    with tarfile.open(source, "r:gz") as archive:
        members = []
        total = 0
        for member in archive:
            total += member.size
            if len(members) >= 100_000 or total > 4 * 1024**3:
                raise ValueError("The desktop archive is too large.")
            members.append(member)
        seen = set()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or member.name.startswith("/") or "\\" in member.name or ":" in member.name
                    or any(part in {".", ".."} for part in member.name.split("/")) or os.path.normcase(member.name) in seen
                    or not (member.isfile() or member.isdir() or member.issym())):
                raise ValueError("The desktop archive contains an unsafe or duplicate path.")
            seen.add(os.path.normcase(member.name))
        # Python's data filter rejects links outside the destination, link-based
        # traversal and special files. The manifest checks all extracted bytes.
        archive.extractall(destination, members=members, filter="data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "extract"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.action == "extract":
        unpack(args.source, args.destination)
    else:
        with tarfile.open(args.destination, "w:gz", compresslevel=3) as archive:
            for item in sorted(args.source.iterdir()):
                archive.add(item, arcname=item.name)


if __name__ == "__main__":
    main()
