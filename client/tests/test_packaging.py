import zipfile

import pytest

from tools import package_release


@pytest.fixture
def release_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    release = tmp_path / "client" / "release"
    release.mkdir(parents=True)
    installer = release / "FocusLedger-Setup-windows-x64.exe"
    installer.write_bytes(b"installer fixture")
    return tmp_path, installer


def assert_checksums(root, names):
    release = root / "client" / "release"
    lines = (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    actual = dict(line.split("  ", 1)[::-1] for line in lines)
    assert set(actual) == set(names)
    for name in names:
        assert actual[name] == package_release.sha256(release / name)


def test_installer_release_does_not_require_server_or_portable_builds(release_tree):
    root, installer = release_tree
    package_release.package_client()
    assert_checksums(root, [installer.name])
    assert not (root / "server").exists()
    assert not (root / "client" / "dist").exists()


def test_optional_portable_release_contains_runtime_and_documentation(release_tree):
    root, installer = release_tree
    dist = root / "client" / "dist"
    runtime = dist / "FocusLedger" / "_internal"
    runtime.mkdir(parents=True)
    (dist / "FocusLedger.exe").write_bytes(b"onefile fixture")
    (dist / "FocusLedger" / "FocusLedger.exe").write_bytes(b"onedir fixture")
    (runtime / "python312.dll").write_bytes(b"runtime fixture")
    (root / "client" / "README.md").write_text("client instructions", encoding="utf-8")
    previews = root / "client" / "docs"
    previews.mkdir()
    (previews / "client-dark-preview.png").write_bytes(b"preview fixture")
    (root / "docs").mkdir()
    (root / "docs" / "THIRD-PARTY-NOTICES.md").write_text("notices", encoding="utf-8")
    package_release.package_client(include_portable=True)
    assert_checksums(root, [installer.name, "FocusLedger.exe", "FocusLedger-windows-x64.zip"])
    with zipfile.ZipFile(installer.parent / "FocusLedger-windows-x64.zip") as archive:
        assert archive.testzip() is None
        assert archive.read("FocusLedger/_internal/python312.dll") == b"runtime fixture"
        assert archive.read("README.md") == b"client instructions"
        assert archive.read("THIRD-PARTY-NOTICES.md") == b"notices"
        assert archive.read("docs/client-dark-preview.png") == b"preview fixture"
    assert (installer.parent / "FocusLedger.exe").read_bytes() == b"onefile fixture"


def test_missing_installer_rejects_release_without_overwriting_manifest(release_tree):
    root, installer = release_tree
    manifest = installer.parent / "SHA256SUMS.txt"
    manifest.write_text("previous release\n", encoding="utf-8")
    installer.unlink()
    with pytest.raises(SystemExit, match="build.ps1"):
        package_release.package_client()
    assert manifest.read_text(encoding="utf-8") == "previous release\n"
