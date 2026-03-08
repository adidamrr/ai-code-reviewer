from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .config import RagConfig
from .kb_loader import collect_document_descriptors, load_namespace_definitions
from .schemas import InventorySource, NamespaceInventory


def build_inventory(config: RagConfig) -> list[NamespaceInventory]:
    descriptors = collect_document_descriptors(config, include_readmes=True)
    grouped: dict[str, list] = defaultdict(list)
    for descriptor in descriptors:
        grouped[descriptor.namespace].append(descriptor)

    inventory: list[NamespaceInventory] = []
    for definition in load_namespace_definitions(config):
        items = grouped.get(definition.namespace, [])
        sources: list[InventorySource] = []
        for source in definition.sources:
            docs = [item for item in items if item.sourceId == source.sourceId]
            chunkable = [item for item in docs if not item.isReadme]
            sources.append(
                InventorySource(
                    sourceId=source.sourceId,
                    title=source.title,
                    url=source.url,
                    documents=len(docs),
                    chunkableDocuments=len(chunkable),
                )
            )

        inventory.append(
            NamespaceInventory(
                namespace=definition.namespace,
                displayName=definition.display_name,
                language=definition.language,
                documents=len(items),
                chunkableDocuments=len([item for item in items if not item.isReadme]),
                ready=len([item for item in items if not item.isReadme]) > 0,
                primary=definition.namespace in config.primary_languages,
                experimental=definition.namespace in config.experimental_languages,
                sources=sources,
            )
        )
    return inventory


def write_inventory(config: RagConfig) -> Path:
    config.build_root.mkdir(parents=True, exist_ok=True)
    output = config.build_root / "inventory.json"
    inventory = [item.model_dump() for item in build_inventory(config)]
    output.write_text(json.dumps(inventory, indent=2, ensure_ascii=True), encoding="utf-8")
    return output
