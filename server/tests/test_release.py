import io
import json
import tarfile
import zipfile

import pytest

from tools import package_release


@pytest.fixture
def server_release(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    server = tmp_path / "server"
    for name in ["Dockerfile", "compose.yaml", "compose.build.yaml", "compose.panel.yaml", "requirements.txt",
                 ".env.example", ".dockerignore", "README.md", "docs/API.md", "build_image.py", "app/main.py"]:
        path = server / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("deployment fixture", encoding="utf-8")
    for name in [".env", "data/focus.sqlite3", "app/__pycache__/main.cpython-312.pyc"]:
        path = server / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not for distribution")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/THIRD-PARTY-NOTICES.md").write_text("notices", encoding="utf-8")
    (server / "docs/server-live-apps-preview.jpg").write_bytes(b"preview fixture")
    release = server / "release"
    release.mkdir()
    image = release / "FocusLedger-server-linux-amd64.tar"
    tag = "focusledger-server:test"
    with tarfile.open(image, "w") as archive:
        for name, value in {
            "manifest.json": [{"Config": "config.json", "RepoTags": [tag], "Layers": []}],
            "config.json": {"os": "linux", "architecture": "amd64"},
        }.items():
            content = json.dumps(value).encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    digest = package_release.sha256(image)
    (release / "image-info.json").write_text(json.dumps({"image": tag, "sha256": digest}), encoding="utf-8")
    (release / "IMAGE-SHA256SUMS.txt").write_text(f"{digest}  {image.name}\n", encoding="utf-8")
    return tmp_path, release


def test_server_can_be_packaged_without_client_and_excludes_local_secrets(server_release):
    root, release = server_release
    package_release.package(server_only=True)
    assert not (root / "client").exists()
    with zipfile.ZipFile(release / "FocusLedger-server-docker.zip") as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert {"server/compose.panel.yaml", "server/app/main.py", "server/.env.example",
                "server/FocusLedger-server-linux-amd64.tar", "server/IMAGE-SHA256SUMS.txt",
                "server/docs/server-live-apps-preview.jpg"} <= names
        assert not any(name.endswith(".sqlite3") or "__pycache__" in name or name == "server/.env" for name in names)
    for line in (release / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ")
        assert package_release.sha256(release / name) == digest


def test_server_package_rejects_an_image_that_no_longer_matches_metadata(server_release):
    _, release = server_release
    with (release / "FocusLedger-server-linux-amd64.tar").open("ab") as stream:
        stream.write(b"unexpected changes")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        package_release.package(server_only=True)
    assert not (release / "FocusLedger-server-docker.zip").exists()
