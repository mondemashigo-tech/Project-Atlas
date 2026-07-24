"""Atlas memory. SQLite is the system-of-record; the Obsidian vault (markdown)
is a generated, human-readable mirror — never the source of truth."""
from .store import MemoryStore

__all__ = ["MemoryStore"]
