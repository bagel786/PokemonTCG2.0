"""Resource-envelope study code isolated from production agents.

Nothing in this package is imported by a competition submission.  The package
exists solely for the pre-registered measurement study described in
``PROTOCOL.md``.
"""

from .stop_policy import FixedWorkStop, WallClockStop

__all__ = ["FixedWorkStop", "WallClockStop"]
__version__ = "0.1.0-dev"
