#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() {
  printf "[kb] %s\n" "$*"
}

fetch() {
  local url="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  say "download: $url"
  curl -fsSL "$url" -o "$dest.tmp"
  mv "$dest.tmp" "$dest"
}

python_latest_text_zip() {
  python3 - <<'PY'
import re
import urllib.request

url = "https://docs.python.org/3/archives/"
html = urllib.request.urlopen(url, timeout=30).read().decode("utf-8", "ignore")
versions = re.findall(r"python-(3\.[0-9]+(?:\.[0-9]+)?)-docs-text\.zip", html)
if not versions:
    raise SystemExit("No python-*-docs-text.zip links found in archives page")
def key(v: str):
    return tuple(int(x) for x in v.split("."))
print(sorted(set(versions), key=key)[-1])
PY
}

extract_zip_to() {
  local zip_path="$1"
  local dest_dir="$2"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  unzip -q -o "$zip_path" -d "$tmp_dir"

  rm -rf "$dest_dir"
  mkdir -p "$(dirname "$dest_dir")"

  local top
  top="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
  if [[ -z "$top" ]]; then
    say "WARN: zip has no top directory; moving whole tmp dir"
    mv "$tmp_dir" "$dest_dir"
    return
  fi

  mv "$top" "$dest_dir"
  rm -rf "$tmp_dir"
}

html_to_text() {
  local in_html="$1"
  local out_txt="$2"
  mkdir -p "$(dirname "$out_txt")"
  python3 - "$in_html" "$out_txt" <<'PY'
import sys
from html.parser import HTMLParser
from pathlib import Path

in_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])

class Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        s = " ".join(data.split())
        if s:
            self.parts.append(s)

html = in_path.read_text(encoding="utf-8", errors="ignore")
parser = Extractor()
parser.feed(html)

text = "\n".join(parser.parts) + "\n"
out_path.write_text(text, encoding="utf-8")
PY
}

main() {
  say "root: $ROOT"

  # Python: latest plain text docs archive
  local py_ver
  py_ver="$(python_latest_text_zip)"
  local py_zip="$ROOT/languages/python/downloads/python-${py_ver}-docs-text.zip"
  fetch "https://docs.python.org/3/archives/python-${py_ver}-docs-text.zip" "$py_zip"
  say "extract python docs: $py_ver"
  extract_zip_to "$py_zip" "$ROOT/languages/python/raw/python-docs-text"

  # JavaScript: ECMA-262 single-page HTML (convert to plain text for indexing)
  local ecma_html="$ROOT/languages/javascript/downloads/ecma262.html"
  fetch "https://tc39.es/ecma262/" "$ecma_html"
  say "convert ecma262.html -> text"
  html_to_text "$ecma_html" "$ROOT/languages/javascript/raw/ecma262/ecma262.txt"

  # Swift: swift-book sources (markdown)
  local swift_zip="$ROOT/languages/swift/downloads/swift-book-main.zip"
  fetch "https://github.com/swiftlang/swift-book/archive/refs/heads/main.zip" "$swift_zip"
  say "extract swift-book"
  extract_zip_to "$swift_zip" "$ROOT/languages/swift/raw/swift-book"

  # C++: working draft PDF (keep as raw download for now)
  local cpp_pdf="$ROOT/languages/cpp/downloads/cpp-draft.pdf"
  fetch "https://timsong-cpp.github.io/cppwp/draft.pdf" "$cpp_pdf"

  # Dart: docs pages (HTML -> text)
  local dart_dir="$ROOT/languages/dart"
  fetch "https://dart.dev/guides/language/language-tour" "$dart_dir/downloads/dart-language-tour.html"
  html_to_text "$dart_dir/downloads/dart-language-tour.html" "$dart_dir/raw/dart-language-tour/language-tour.txt"

  fetch "https://dart.dev/guides/language/effective-dart" "$dart_dir/downloads/dart-effective-dart.html"
  html_to_text "$dart_dir/downloads/dart-effective-dart.html" "$dart_dir/raw/effective-dart/effective-dart.txt"

  fetch "https://dart.dev/tools/linter-rules" "$dart_dir/downloads/dart-linter-rules.html"
  html_to_text "$dart_dir/downloads/dart-linter-rules.html" "$dart_dir/raw/dart-linter-rules/linter-rules.txt"

  say "done"
  say "Downloaded files are in gitignored folders under rag-ml/kb/languages/*/(downloads|raw)/"
}

main "$@"
