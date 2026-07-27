"""Atlas Live — the interactive web application layer over the Atlas engine.

This package is a thin, read-mostly surface: it reads the SQLite source of truth
and the typed event spine, streams events to the browser, and exposes a grounded
conversation endpoint. It never rewrites research logic and never touches capital.
The FastAPI app is optional; the core lab runs without it.
"""
from .app import create_app

__all__ = ["create_app"]
