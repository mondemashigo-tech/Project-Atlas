"""`python -m atlas` -> the Atlas CLI (thin adapter over the library)."""
import sys

from .interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
