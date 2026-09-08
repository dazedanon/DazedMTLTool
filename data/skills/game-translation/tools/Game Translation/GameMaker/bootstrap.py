"""Download a pinned official UTMT CLI release into this toolkit (stdlib only)."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.9.2.0"
REPO = "UnderminersTeam/UndertaleModTool"
ARCHIVE_NAME = f"UTMT_CLI_v{VERSION}-Windows.zip"
ARCHIVE_SHA256 = "e7573e45d107be34f81f955c6e4afc3c7c8f2628e5a6f307a871e3825b3dfb40"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "GameMaker-Text-Tools/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main():
    vendor = ROOT / "vendor"
    vendor.mkdir(exist_ok=True)
    url = f"https://github.com/{REPO}/releases/download/{VERSION}/{ARCHIVE_NAME}"
    archive = vendor / ARCHIVE_NAME
    if not archive.exists():
        archive.write_bytes(fetch(url))
    digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != "sha256:" + ARCHIVE_SHA256:
        raise RuntimeError("Release archive SHA256 does not match GitHub's asset digest")
    target = vendor / "utmt"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not (target / name).resolve().is_relative_to(target.resolve()):
                raise RuntimeError(f"Unsafe archive entry: {name}")
        z.extractall(target)
    source = vendor / "source-reference"
    source.mkdir(exist_ok=True)
    for path in ["LICENSE.txt", "UndertaleModLib/Models/UndertaleCode.cs", "UndertaleModLib/Models/UndertaleGeneralInfo.cs", "UndertaleModLib/Models/UndertaleFont.cs", "UndertaleModLib/Models/UndertaleString.cs", "UndertaleModLib/UndertaleData.cs", "UndertaleModCli/Program.cs"]:
        (source / Path(path).name).write_bytes(fetch(f"https://raw.githubusercontent.com/{REPO}/{VERSION}/{path}"))
    manifest = {"version": VERSION, "url": url, "sha256": digest.removeprefix("sha256:"), "release": f"https://github.com/{REPO}/releases/tag/{VERSION}"}
    (vendor / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
