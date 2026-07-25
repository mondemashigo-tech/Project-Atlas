"""The autonomous research laboratory (Volume 5): a governed loop that proposes,
tests, and records — within a sandbox, under an autonomy ceiling, and never
promoting anything to capital without a human."""
from .loop import ResearchLoop, MAX_AUTONOMY
from .decay import decay_check, monitor

__all__ = ["ResearchLoop", "MAX_AUTONOMY", "decay_check", "monitor"]
