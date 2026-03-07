#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def say(msg: str) -> None:
    print(f"[kb] {msg}")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> None:
    # shutil.copytree requires dst not exist; we want idempotent behavior.
    for root, _, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        out_dir = dst / rel
        ensure_dir(out_dir)
        for name in files:
            in_path = root_path / name
            out_path = out_dir / name
            shutil.copy2(in_path, out_path)


def copy_matching_files(src_root: Path, dst_root: Path, *, suffixes: tuple[str, ...]) -> int:
    count = 0
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(src_root)
        out_path = dst_root / rel
        ensure_dir(out_path.parent)
        shutil.copy2(path, out_path)
        count += 1
    return count


def build_python(root: Path) -> None:
    lang = root / "languages" / "python"
    raw = lang / "raw" / "python-docs-text"
    out = lang / "docs" / "python-docs-text"
    if not raw.exists():
        raise SystemExit("Python raw docs not found. Run: ./rag-ml/kb/pull-docs.sh")
    say("python: copy raw text archive -> docs/python-docs-text/")
    reset_dir(out)
    copy_tree(raw, out)
    say(f"python: files={sum(1 for _ in out.rglob('*.txt'))}")


def build_javascript(root: Path) -> None:
    lang = root / "languages" / "javascript"
    raw_txt = lang / "raw" / "ecma262" / "ecma262.txt"
    out_dir = lang / "docs" / "ecma-262"
    if not raw_txt.exists():
        raise SystemExit("JS raw ecma262.txt not found. Run: ./rag-ml/kb/pull-docs.sh")
    say("javascript: copy ecma262.txt -> docs/ecma-262/")
    reset_dir(out_dir)
    shutil.copy2(raw_txt, out_dir / "ecma262.txt")
    say(f"javascript: bytes={ (out_dir / 'ecma262.txt').stat().st_size }")


def build_swift(root: Path) -> None:
    lang = root / "languages" / "swift"
    raw = lang / "raw" / "swift-book"
    out = lang / "docs" / "swift-book-repo"
    if not raw.exists():
        raise SystemExit("Swift raw swift-book not found. Run: ./rag-ml/kb/pull-docs.sh")
    say("swift: copy TSPL.docc markdown -> docs/swift-book-repo/")
    reset_dir(out)
    src_docc = raw / "TSPL.docc"
    copied = copy_matching_files(src_docc, out / "TSPL.docc", suffixes=(".md",))
    # Also include LICENSE for attribution.
    if (raw / "LICENSE.txt").exists():
        shutil.copy2(raw / "LICENSE.txt", out / "LICENSE.txt")
    say(f"swift: md_files={copied}")


def build_cpp(root: Path, *, pages_per_file: int) -> None:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Missing dependency 'pypdf'. Install with: python3 -m pip install -r rag-ml/requirements.txt"
        ) from exc

    lang = root / "languages" / "cpp"
    pdf_path = lang / "downloads" / "cpp-draft.pdf"
    out_dir = lang / "docs" / "cpp-working-draft-pdf"
    if not pdf_path.exists():
        raise SystemExit("C++ draft PDF not found. Run: ./rag-ml/kb/pull-docs.sh")

    say("cpp: extract pdf -> docs/cpp-working-draft-pdf/ (split by pages)")
    reset_dir(out_dir)

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    say(f"cpp: pages={total}, pages_per_file={pages_per_file}")

    def out_name(start_page_0: int, end_page_0: int) -> str:
        # Human-friendly 1-based page numbers in file name.
        return f"cpp-draft.p{start_page_0+1:04d}-p{end_page_0+1:04d}.txt"

    start = 0
    while start < total:
        end = min(total - 1, start + pages_per_file - 1)
        out_path = out_dir / out_name(start, end)
        say(f"cpp: write {out_path.name}")
        with out_path.open("w", encoding="utf-8", errors="ignore") as f:
            for page_i in range(start, end + 1):
                page = reader.pages[page_i]
                text = page.extract_text() or ""
                f.write(f"\n\n===== PAGE {page_i+1} =====\n\n")
                f.write(text)
        start = end + 1


def build_dart(root: Path) -> None:
    lang = root / "languages" / "dart"
    raw_root = lang / "raw"
    out_root = lang / "docs"
    if not raw_root.exists():
        raise SystemExit("Dart raw docs not found. Run: ./rag-ml/kb/pull-docs.sh")

    say("dart: copy raw text pages -> docs/<sourceId>/")
    for source_dir in sorted([p for p in raw_root.iterdir() if p.is_dir()]):
        dest = out_root / source_dir.name
        reset_dir(dest)
        copy_tree(source_dir, dest)
        say(f"dart: {source_dir.name} files={sum(1 for _ in dest.rglob('*.txt'))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build commit-ready KB docs from raw downloads.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent), help="rag-ml/kb directory")
    parser.add_argument("--cpp-pages-per-file", type=int, default=200, help="Split C++ PDF text into N pages per file")
    args = parser.parse_args()

    kb_root = Path(args.root).resolve()
    if kb_root.name != "kb":
        say(f"WARN: root looks unusual: {kb_root}")

    build_python(kb_root)
    build_javascript(kb_root)
    build_swift(kb_root)
    build_cpp(kb_root, pages_per_file=args.cpp_pages_per_file)
    build_dart(kb_root)
    say("done")


if __name__ == "__main__":
    main()
