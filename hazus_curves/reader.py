"""Read and evaluate Hazus curves.

    >>> from hazus_curves import connect, get_curve, damage
    >>> con = connect()
    >>> damage(con, "fl-6.1-structure-129", 3.5)   # depth 3.5 ft
    43.5

Interpolation is piecewise-linear between published points, which is the convention
Hazus itself documents for its depth-damage functions. Values outside a curve's
published domain raise rather than extrapolate: a curve that stops at 24 ft says
nothing about 30 ft, and guessing would fabricate a number.
"""

import sqlite3
from bisect import bisect_left
from pathlib import Path
from typing import Optional

DEFAULT_DB_NAME = "hazus_curves.sqlite"


class CurveError(Exception):
    """Raised when a curve cannot be found or evaluated as asked."""


def default_db_path() -> Path:
    """Where `hazus-curves install` puts the database by default."""
    return Path.home() / ".hazus_curves" / DEFAULT_DB_NAME


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path) if path else default_db_path()
    if not path.exists():
        raise CurveError(
            f"no database at {path}. Run:  hazus-curves install --perils fl"
        )
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_curves(con, peril=None, damage_type=None, occupancy=None,
                hazus_version=None, building_type=None, limit=None):
    """Return curve metadata rows matching the given filters."""
    where, params = [], []
    for col, val in (("peril", peril), ("damage_type", damage_type),
                     ("occupancy", occupancy), ("hazus_version", hazus_version),
                     ("building_type", building_type)):
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    sql = "SELECT * FROM curves"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY curve_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in con.execute(sql, params)]


def get_curve(con, curve_id: str) -> dict:
    """Return one curve with its points and attributes attached."""
    row = con.execute("SELECT * FROM curves WHERE curve_id = ?",
                      (curve_id,)).fetchone()
    if row is None:
        raise CurveError(f"no such curve: {curve_id!r}")
    curve = dict(row)
    curve["points"] = [(r["x"], r["y"]) for r in con.execute(
        "SELECT x, y FROM curve_points WHERE curve_id = ? ORDER BY x", (curve_id,))]
    curve["attributes"] = {r["key"]: r["value"] for r in con.execute(
        "SELECT key, value FROM curve_attributes WHERE curve_id = ?", (curve_id,))}
    kind = con.execute(
        "SELECT * FROM curve_kind WHERE peril = ? AND damage_type = ?",
        (curve["peril"], curve["damage_type"])).fetchone()
    curve["kind"] = dict(kind) if kind else None
    return curve


def damage(con, curve_id: str, x: float) -> float:
    """Evaluate a curve at ``x`` by piecewise-linear interpolation.

    Raises rather than extrapolating outside the curve's published domain, and rather
    than interpolating across a gap where the source value was NULL.
    """
    points = [(r["x"], r["y"]) for r in con.execute(
        "SELECT x, y FROM curve_points WHERE curve_id = ? ORDER BY x", (curve_id,))]
    if not points:
        raise CurveError(f"no such curve: {curve_id!r}")
    return interpolate(points, x, curve_id=curve_id)


def interpolate(points, x: float, curve_id: str = "<curve>") -> float:
    """Piecewise-linear interpolation over (x, y) pairs sorted by x."""
    xs = [p[0] for p in points]
    lo, hi = xs[0], xs[-1]
    if not lo <= x <= hi:
        raise CurveError(
            f"{curve_id}: x={x} is outside the published domain [{lo}, {hi}]. "
            f"Hazus does not define this curve there, and extrapolating would "
            f"invent a value."
        )
    i = bisect_left(xs, x)
    if xs[i] == x:
        y = points[i][1]
        if y is None:
            raise CurveError(f"{curve_id}: no published value at x={x}")
        return float(y)
    x0, y0 = points[i - 1]
    x1, y1 = points[i]
    if y0 is None or y1 is None:
        raise CurveError(
            f"{curve_id}: cannot interpolate across a gap between x={x0} and x={x1} "
            f"-- the source has no value at one endpoint."
        )
    return float(y0) + (float(y1) - float(y0)) * (x - x0) / (x1 - x0)
