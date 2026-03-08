from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import RagConfig
from .schemas import DocumentDescriptor, NamespaceManifest, RootKbManifest, SourceManifest

TEXT_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class NamespaceDefinition:
    namespace: str
    display_name: str
    language: str | None
    manifest_path: Path
    doc_roots: tuple[Path, ...]
    sources: tuple[SourceManifest, ...]
    notes: str | None


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_root_manifest(config: RagConfig) -> RootKbManifest:
    return RootKbManifest.model_validate(_read_json(config.kb_root / "manifest.json"))


def load_namespace_definitions(config: RagConfig) -> list[NamespaceDefinition]:
    root = load_root_manifest(config)
    definitions: list[NamespaceDefinition] = []

    for entry in root.languages:
        if entry.slug not in config.supported_languages:
            continue
        manifest_path = config.kb_root / entry.path
        manifest = NamespaceManifest.model_validate(_read_json(manifest_path))
        doc_roots = tuple((manifest_path.parent / root_path).resolve() for root_path in manifest.docRoots)
        definitions.append(
            NamespaceDefinition(
                namespace=entry.slug,
                display_name=manifest.displayName,
                language=entry.slug,
                manifest_path=manifest_path,
                doc_roots=doc_roots,
                sources=tuple(manifest.sources),
                notes=manifest.notes,
            )
        )

    shared_manifest_path = config.kb_root / "shared" / "security-pack" / "manifest.json"
    if shared_manifest_path.exists():
        manifest = NamespaceManifest.model_validate(_read_json(shared_manifest_path))
        definitions.append(
            NamespaceDefinition(
                namespace="security-pack",
                display_name=manifest.displayName,
                language=None,
                manifest_path=shared_manifest_path,
                doc_roots=tuple((shared_manifest_path.parent / root_path).resolve() for root_path in manifest.docRoots),
                sources=tuple(manifest.sources),
                notes=manifest.notes,
            )
        )

    return definitions


def _infer_source_id(doc_root: Path, file_path: Path, definition: NamespaceDefinition) -> str:
    relative = file_path.relative_to(doc_root)
    if relative.name == "00-readme.md":
        return "readme"

    if relative.parts:
        candidate = relative.parts[0]
        if any(source.sourceId == candidate for source in definition.sources):
            return candidate

    if len(definition.sources) == 1:
        return definition.sources[0].sourceId

    return relative.parts[0] if relative.parts else "manual"


def _resolve_source(source_id: str, definition: NamespaceDefinition) -> tuple[str, str]:
    source = next((item for item in definition.sources if item.sourceId == source_id), None)
    if source:
        return source.title, source.url
    return (source_id.replace("-", " ").title(), definition.manifest_path.as_uri())


def collect_document_descriptors(config: RagConfig, *, include_readmes: bool = False) -> list[DocumentDescriptor]:
    descriptors: list[DocumentDescriptor] = []
    for definition in load_namespace_definitions(config):
        for doc_root in definition.doc_roots:
            if not doc_root.exists():
                continue
            for file_path in sorted(doc_root.rglob("*")):
                if not file_path.is_file() or file_path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                is_readme = file_path.name == "00-readme.md"
                if is_readme and not include_readmes:
                    continue
                source_id = _infer_source_id(doc_root, file_path, definition)
                source_title, source_url = _resolve_source(source_id, definition)
                descriptors.append(
                    DocumentDescriptor(
                        namespace=definition.namespace,
                        language=definition.language,
                        displayName=definition.display_name,
                        sourceId=source_id,
                        sourceTitle=source_title,
                        sourceUrl=source_url,
                        docPath=str(file_path.resolve()),
                        isReadme=is_readme,
                    )
                )
    return descriptors
