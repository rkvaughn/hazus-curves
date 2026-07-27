"""Open database of FEMA Hazus damage and vulnerability curves.

Not affiliated with or endorsed by FEMA. "Hazus" is a trademark of the Federal
Emergency Management Agency.
"""

from .reader import (
    CurveError,
    connect,
    damage,
    default_db_path,
    get_curve,
    interpolate,
    load_curves,
)

__version__ = "0.1.1"

__all__ = [
    "CurveError",
    "connect",
    "damage",
    "default_db_path",
    "get_curve",
    "interpolate",
    "load_curves",
    "__version__",
]
