"""The Scout — sources trading ideas from the outside world and turns them into
pre-registered hypotheses Atlas can test.

Pipeline:  fetch (web/file) -> extract rules -> build hypothesis -> queue/test.

Humility by design (Volume 1): Atlas does not assume it already knows the best
strategy. The Scout lets it ingest what other people claim to have found and put
those claims through the same ruthless validation as its own ideas.
"""
from .scout import Scout

__all__ = ["Scout"]
