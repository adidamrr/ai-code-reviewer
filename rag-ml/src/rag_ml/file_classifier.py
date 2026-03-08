from __future__ import annotations

from .schemas import RagFile


FILE_CLASS_PATTERNS = {
    "docs": (
        "readme",
        "/docs/",
        ".md",
        ".rst",
        "changelog",
        "license",
    ),
    "resource": (
        "/localization/",
        "/translations/",
        "_strings_",
        "/l10n/",
        ".json",
        ".arb",
        ".yaml",
        ".yml",
    ),
    "generated": (
        "/generated/",
        ".g.dart",
        ".pb.dart",
        ".gen.py",
        "_generated.py",
    ),
    "test": (
        "/tests/",
        "test_",
        "_test.py",
        "_test.dart",
    ),
}


def classify_file(file: RagFile) -> str:
    if file.fileRole:
        return file.fileRole
    path = file.path.lower()
    for file_class, patterns in FILE_CLASS_PATTERNS.items():
        if any(pattern in path for pattern in patterns):
            return file_class
    if any(token in path for token in ("/api/", "/routes/", "handler", "endpoint")):
        return "api"
    if any(token in path for token in ("/repositories/", "/repository/", "/dao/", "/queries/")):
        return "repository"
    if any(token in path for token in ("/services/", "/service/", "/use_cases/", "/usecases/")):
        return "logic"
    if any(token in path for token in ("/models/", "/schemas/", "/entities/")):
        return "model"
    return "logic"


def supports_full_review(file_class: str) -> bool:
    return file_class in {"logic", "api", "repository", "model"}
