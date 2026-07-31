"""Config-driven strategy templates.

Importing this package registers every template with the Strategy registry, so
`Strategy.create(cfg)` can build any of them by its `template` key.
"""
from . import trend_continuation  # noqa: F401
from . import mean_reversion      # noqa: F401
from . import breakout            # noqa: F401
from . import orb                 # noqa: F401
from . import composed            # noqa: F401
from . import bos_retrace         # noqa: F401
