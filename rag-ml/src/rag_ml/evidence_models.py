from __future__ import annotations


def code_ref(task_id: str, index: int) -> str:
    return f"code:{task_id}:{index}"


def rule_ref(task_id: str, index: int) -> str:
    return f"rule:{task_id}:{index}"


def history_ref(task_id: str, index: int) -> str:
    return f"history:{task_id}:{index}"


def doc_ref(chunk_id: str) -> str:
    return f"doc:{chunk_id}"


def unwrap_doc_ref(value: str) -> str | None:
    if not value.startswith("doc:"):
        return None
    chunk_id = value.split(":", 1)[1]
    return chunk_id or None
