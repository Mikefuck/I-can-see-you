"""Build distributable archives from the completed client and server."""
import argparse
import hashlib
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package_client(include_portable=False):
    """Publish the installer without requiring a server image or a portable build."""
    client_root = ROOT / "client"
    client = client_root / "dist" / "FocusLedger"
    installer = client_root / "release" / "FocusLedger-Setup-windows-x64.exe"
    if not installer.is_file():
        raise SystemExit(f"Missing {installer}. Run client/build.ps1 first.")
    outputs = [installer]
    if include_portable:
        single_exe = client_root / "dist" / "FocusLedger.exe"
        for path in [single_exe, client / "FocusLedger.exe"]:
            if not path.is_file():
                raise SystemExit(f"Missing {path}. Run client/build.ps1 -Package all first.")
        released_exe = client_root / "release" / "FocusLedger.exe"
        shutil.copy2(single_exe, released_exe)
        client_zip = client_root / "release" / "FocusLedger-windows-x64.zip"
        with zipfile.ZipFile(client_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(client.rglob("*")):
                if path.is_file():
                    archive.write(path, Path("FocusLedger") / path.relative_to(client))
            archive.write(client_root / "README.md", "README.md")
            archive.write(ROOT / "docs" / "THIRD-PARTY-NOTICES.md", "THIRD-PARTY-NOTICES.md")
            for path in sorted((client_root / "docs").glob("*.png")):
                archive.write(path, Path("docs") / path.name)
        with zipfile.ZipFile(client_zip) as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f"Corrupt ZIP: {client_zip}")
        outputs.extend([released_exe, client_zip])
    (client_root / "release" / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in outputs), encoding="utf-8")
    for path in outputs:
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1024 / 1024:.1f} MiB")


def package(server_only=False):
    client_root = ROOT / "client"
    server = ROOT / "server"
    client = client_root / "dist" / "FocusLedger"
    single_exe = client_root / "dist" / "FocusLedger.exe"
    image = server / "release" / "FocusLedger-server-linux-amd64.tar"
    image_info = server / "release" / "image-info.json"
    required = [image, image_info, server / "release" / "IMAGE-SHA256SUMS.txt"]
    if not server_only:
        required.extend([client / "FocusLedger.exe", single_exe,
                         client_root / "release" / "FocusLedger-Setup-windows-x64.exe"])
    for path in required:
        if not path.is_file():
            instructions = "server/build_image.py" if server_only else "client/build.ps1 -Package all and server/build_image.py"
            raise SystemExit(f"Missing {path}. Run {instructions} first.")
    metadata = json.loads(image_info.read_text(encoding="utf-8"))
    if metadata["sha256"] != sha256(image):
        raise SystemExit("Image checksum mismatch; rebuild the server image.")
    with tarfile.open(image) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        if len(manifest) != 1 or metadata["image"] not in manifest[0]["RepoTags"]:
            raise SystemExit("Image archive tag does not match image-info.json.")
        config = json.load(archive.extractfile(manifest[0]["Config"]))
        if (config["os"], config["architecture"]) != ("linux", "amd64"):
            raise SystemExit("Expected a linux/amd64 Docker image.")
    # Only deployment files belong in the server archive. This also prevents
    # recursively including server/release while its ZIP is being written.
    deployment_files = [server / name for name in [
        "Dockerfile", "compose.yaml", "compose.build.yaml", "compose.panel.yaml", "requirements.txt", ".env.example",
        ".dockerignore", "README.md", "docs/API.md", "build_image.py",
    ]]
    deployment_files.extend(path for path in sorted((server / "app").rglob("*"))
                            if path.is_file() and "__pycache__" not in path.parts
                            and path.suffix not in {".pyc", ".pyo"})
    deployment_files.extend(path for path in sorted((server / "docs").iterdir())
                            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    assert all(path.is_file() for path in deployment_files), "Missing server deployment files"
    (server / "release").mkdir(parents=True, exist_ok=True)
    if not server_only:
        package_client(include_portable=True)
    server_zip = server / "release" / "FocusLedger-server-docker.zip"
    with zipfile.ZipFile(server_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in deployment_files:
            archive.write(path, Path("server") / path.relative_to(server))
        archive.write(ROOT / "docs" / "THIRD-PARTY-NOTICES.md", "server/docs/THIRD-PARTY-NOTICES.md")
        for path in [image, image_info, server / "release" / "IMAGE-SHA256SUMS.txt"]:
            archive.write(path, Path("server") / path.name)
    with zipfile.ZipFile(server_zip) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"Corrupt ZIP: {server_zip}")
    checksums = []
    for path in [image, server_zip]:
        checksums.append(f"{sha256(path)}  {path.name}\n")
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1024 / 1024:.1f} MiB")
    (server / "release" / "SHA256SUMS.txt").write_text("".join(checksums), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--client-only", action="store_true", help="Package the client without touching server releases")
    targets.add_argument("--server-only", action="store_true", help="Package the server without requiring client builds")
    parser.add_argument("--portable", action="store_true", help="Also publish portable client builds (with --client-only)")
    args = parser.parse_args()
    if args.portable and not args.client_only:
        parser.error("--portable requires --client-only; a full release already includes portable builds")
    if args.client_only:
        package_client(include_portable=args.portable)
    else:
        package(server_only=args.server_only)
