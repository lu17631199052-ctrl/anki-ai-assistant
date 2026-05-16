"""Notebook management — persistent, multi-file document storage for AI grounding.

Notebooks are stored as JSON files under ADDON_DIR/notebooks/.
Each notebook contains one or more files whose text has been extracted.
The index file _index.json provides fast listing without loading all data.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..config import ADDON_DIR

NOTEBOOKS_DIR = os.path.join(ADDON_DIR, "notebooks")
INDEX_PATH = os.path.join(NOTEBOOKS_DIR, "_index.json")

MAX_CONTEXT_CHARS = 30000
TRUNCATE_HEAD = 15000
TRUNCATE_TAIL = 15000


@dataclass
class NotebookFile:
    name: str
    text: str
    char_count: int = 0

    def __post_init__(self):
        if not self.char_count:
            self.char_count = len(self.text)


@dataclass
class Notebook:
    id: str
    name: str
    files: list[NotebookFile] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = _now()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_chars(self) -> int:
        return sum(f.char_count for f in self.files)

    def combined_text(self) -> str:
        """Return all file texts concatenated, truncated if too long."""
        parts: list[str] = []
        for f in self.files:
            parts.append(f"--- {f.name} ---\n{f.text}")
        full = "\n\n".join(parts)
        if len(full) > MAX_CONTEXT_CHARS:
            head = full[:TRUNCATE_HEAD]
            tail = full[-TRUNCATE_TAIL:]
            full = (
                f"{head}\n\n... [中间省略 {len(full) - TRUNCATE_HEAD - TRUNCATE_TAIL} 字] ...\n\n{tail}"
            )
        return full

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "file_count": self.file_count,
            "total_chars": self.total_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir() -> None:
    os.makedirs(NOTEBOOKS_DIR, exist_ok=True)


def _load_index() -> list[dict]:
    _ensure_dir()
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_index(data: list[dict]) -> None:
    _ensure_dir()
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _notebook_path(notebook_id: str) -> str:
    return os.path.join(NOTEBOOKS_DIR, f"{notebook_id}.json")


def _save_notebook(nb: Notebook) -> None:
    _ensure_dir()
    data = {
        "id": nb.id,
        "name": nb.name,
        "files": [{"name": f.name, "text": f.text, "char_count": f.char_count} for f in nb.files],
        "created_at": nb.created_at,
        "updated_at": nb.updated_at,
    }
    with open(_notebook_path(nb.id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Update index
    index = _load_index()
    summary = nb.to_summary()
    for i, entry in enumerate(index):
        if entry["id"] == nb.id:
            index[i] = summary
            break
    else:
        index.append(summary)
    _save_index(index)


def list_notebooks() -> list[dict]:
    """Return list of notebook summaries from the index."""
    return _load_index()


def get_notebook(notebook_id: str) -> Optional[Notebook]:
    """Load a full notebook by ID. Returns None if not found."""
    path = _notebook_path(notebook_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        files = [NotebookFile(name=f["name"], text=f["text"], char_count=f["char_count"])
                  for f in data.get("files", [])]
        return Notebook(
            id=data["id"],
            name=data["name"],
            files=files,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def create_notebook(name: str, files: Optional[list[tuple[str, str]]] = None) -> Notebook:
    """Create a new notebook with optional initial files.

    files: list of (filename, extracted_text)
    """
    nb = Notebook(
        id=uuid.uuid4().hex[:12],
        name=name,
    )
    if files:
        for fname, ftext in files:
            nb.files.append(NotebookFile(name=fname, text=ftext))
    nb.updated_at = _now()
    _save_notebook(nb)
    return nb


def add_files_to_notebook(notebook_id: str, files: list[tuple[str, str]]) -> Optional[Notebook]:
    """Append files to an existing notebook.

    files: list of (filename, extracted_text)
    """
    nb = get_notebook(notebook_id)
    if nb is None:
        return None
    for fname, ftext in files:
        nb.files.append(NotebookFile(name=fname, text=ftext))
    nb.updated_at = _now()
    _save_notebook(nb)
    return nb


def delete_notebook(notebook_id: str) -> bool:
    """Delete a notebook and its data file. Returns True if deleted."""
    path = _notebook_path(notebook_id)
    deleted = False
    try:
        os.remove(path)
        deleted = True
    except FileNotFoundError:
        pass
    except OSError:
        return False

    index = _load_index()
    index = [e for e in index if e["id"] != notebook_id]
    _save_index(index)
    return deleted


def get_combined_text(notebook_id: str) -> Optional[str]:
    """Get combined text of all files in a notebook (for prompt injection)."""
    nb = get_notebook(notebook_id)
    if nb is None:
        return None
    return nb.combined_text()
