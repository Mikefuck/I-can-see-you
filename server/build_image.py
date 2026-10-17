"""Build and export a Linux image using Docker (run on Linux or Docker Desktop)."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = "focusledger-server:2026.10.17-r15"
ARCHIVE = "FocusLedger-server-linux-amd64.tar"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker", help="Docker executable")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--network", help="Optional build network, e.g. host")
    args = parser.parse_args()
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    build = [args.docker, "build", "--platform", "linux/amd64", "--tag", args.image]
    if args.network:
        build += ["--network", args.network]
    subprocess.run([*build, str(ROOT)], check=True)
    info = json.loads(subprocess.check_output(
        [args.docker, "image", "inspect", args.image], text=True
    ))[0]
    if (info["Os"], info["Architecture"]) != ("linux", "amd64"):
        raise RuntimeError("Expected a linux/amd64 image")
    archive = release / ARCHIVE
    temporary = archive.with_suffix(".tar.tmp")
    try:
        subprocess.run([args.docker, "image", "save", "--output", str(temporary), args.image], check=True)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (release / "IMAGE-SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    (release / "image-info.json").write_text(json.dumps({
        "image": args.image,
        "image_id": info["Id"],
        "platform": "linux/amd64",
        "created": info["Created"],
        "archive": archive.name,
        "sha256": digest,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Ready: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
