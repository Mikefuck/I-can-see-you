"""Read-only checks of Git source files and local documentation links.

Uses only the Python standard library. Includes tracked files and unignored new
files; does not inspect Git history, modify files, or contact the network.
"""

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 10 * 1024 * 1024
LOCAL_DIRECTORIES = {
    ".runtime", ".venv", "venv", ".gradle", ".kotlin", ".cxx",
    "__pycache__", ".pytest_cache", "node_modules", "build", "dist",
    ".claude", ".idea", ".vscode",
}
LOCAL_NAMES = {"local.properties", "signing.properties", "key.properties"}
PRIVATE_SUFFIXES = {
    ".jks", ".keystore", ".pem", ".key", ".p12", ".pfx", ".log",
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite-shm",
    ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
}
RELEASE_SUFFIXES = {".exe", ".msi", ".apk", ".aab", ".zip", ".tar", ".gz"}
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "API secret": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
}
MARKDOWN_LINK = re.compile(r'!?\[[^\]\n]*\]\(<?([^\s)>]+)>?(?:\s+"[^"]*")?\)')


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"src", "href"} and value:
                self.links.append(value)


def source_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    return sorted(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")) - {""})


def check_path(name):
    path = PurePosixPath(name)
    if any(part in LOCAL_DIRECTORIES for part in path.parts):
        return "local environment, cache, build or editor file"
    if path.name in LOCAL_NAMES:
        return "machine-specific configuration"
    if path.name == ".env" or (path.name.startswith(".env.") and not path.name.endswith(".example")):
        return "environment credentials; publish an .env.example instead"
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        return "credential, log or runtime data file"
    if path.parts[:2] in {("server", "data"), ("server", "focus-data")}:
        return "server runtime data"
    if "release" in path.parts and path.suffix.lower() in RELEASE_SUFFIXES:
        return "binary release asset; upload it to GitHub Releases"
    return None


def document_links(text):
    # Command examples and inline code often contain Markdown-like syntax.
    text = re.sub(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*$", "", text, flags=re.M | re.S)
    text = re.sub(r"`[^`\n]+`", "", text)
    links = MARKDOWN_LINK.findall(text)
    html = HtmlLinks()
    html.feed(text)
    return links + html.links


def check_link(document, target, published):
    url = urlsplit(target)
    if url.scheme or url.netloc or not url.path:
        return None
    if url.path.startswith("/"):
        return f"absolute local link: {target}"
    resolved = (document.parent / unquote(url.path)).resolve()
    try:
        relative = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return f"link outside the repository: {target}"
    if not resolved.exists():
        return f"missing local link: {target}"
    if resolved.is_file() and relative not in published:
        return f"link to a file excluded from the source repository: {target}"
    if resolved.is_dir() and not any(name.startswith(relative + "/") for name in published):
        return f"link to a directory excluded from the source repository: {target}"
    return None


def main():
    try:
        files = source_files()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Cannot read the Git file list: {exc}", file=sys.stderr)
        return 1
    published = {name for name in files if (ROOT / name).is_file()}
    errors = []
    documents = 0
    for name in sorted(published):
        path = ROOT / name
        problem = check_path(name)
        if problem:
            errors.append(f"{name}: {problem}")
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{name}: exceeds the 10 MiB source-file limit")
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                # Never print a matching credential or its source line.
                errors.append(f"{name}: possible {label}; review privately")
        if path.suffix.lower() == ".md":
            documents += 1
            for target in document_links(content.decode("utf-8-sig")):
                problem = check_link(path, target, published)
                if problem:
                    errors.append(f"{name}: {problem}")
    for required in ("README.md", "LICENSE", ".github/CONTRIBUTING.md", ".github/SECURITY.md"):
        if required not in published:
            errors.append(f"{required}: missing from the source file list")
    if errors:
        print("Repository checks failed:")
        for error in sorted(set(errors)):
            print(f"  - {error}")
        return 1
    print(f"Repository checks passed: {len(published)} files, {documents} Markdown documents.")
    print("Checked local files only; manually review content and Git history before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
