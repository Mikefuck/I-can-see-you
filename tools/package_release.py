"""Build distributable archives from the completed client and server."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package():
    client_root = ROOT / "client"
    server = ROOT / "server"
    client = client_root / "dist" / "FocusLedger"
    assert (client / "FocusLedger.exe").exists(), "Build the Windows client first"
    # Only deployment files belong in the server archive. This also prevents
    # recursively including server/release while its ZIP is being written.
    deployment_files = [server / name for name in [
        "Dockerfile", "compose.yaml", "requirements.txt", ".env.example",
        ".dockerignore", "README.md", "docs/API.md",
    ]]
    deployment_files.extend(path for path in sorted((server / "app").rglob("*"))
                            if path.is_file() and "__pycache__" not in path.parts
                            and path.suffix not in {".pyc", ".pyo"})
    assert all(path.is_file() for path in deployment_files), "Missing server deployment files"
    for directory in [client_root / "release", server / "release"]:
        directory.mkdir(parents=True, exist_ok=True)
    client_zip = client_root / "release" / "FocusLedger-windows-x64.zip"
    with zipfile.ZipFile(client_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(client.rglob("*")):
            if path.is_file():
                archive.write(path, Path("FocusLedger") / path.relative_to(client))
        archive.write(client_root / "README.md", "README.md")
        archive.write(ROOT / "docs" / "THIRD-PARTY-NOTICES.md", "THIRD-PARTY-NOTICES.md")
    server_zip = server / "release" / "FocusLedger-server-docker.zip"
    with zipfile.ZipFile(server_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in deployment_files:
            archive.write(path, Path("server") / path.relative_to(server))
        archive.write(ROOT / "docs" / "THIRD-PARTY-NOTICES.md", "server/docs/THIRD-PARTY-NOTICES.md")
    for path in [client_zip, server_zip]:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (path.parent / "SHA256SUMS.txt").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    package()
