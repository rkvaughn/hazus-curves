"""Guard against the publish step silently dropping columns.

tests/test_losslessness.py checks that no *source* column is lost on the way into the
tidy model. This file checks the other end of the pipeline: that no column produced by
the build scripts is lost on the way out into the published database.

That gap was real. `defect_verified` -- the result of independently verifying FEMA's
disclosed hurricane defect -- was computed by verify_hurricane_defect.py, written to
dist/curves_hu.parquet, and then quietly discarded by build_db.py, which projects each
table onto the columns declared in schema.py. Users got a database missing the column
the documentation told them to use.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
sys.path.insert(0, str(REPO))

from hazus_curves.schema import TABLES  # noqa: E402

duckdb = pytest.importorskip("duckdb")

# Build-stage artifacts and the published table they feed into.
INTERMEDIATE = {
    "curves_hu.parquet": "curves",
    "curve_attributes_hu.parquet": "curve_attributes",
    "curve_points_hu.parquet": "curve_points",
}


def _columns(path: Path):
    con = duckdb.connect()
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
    con.close()
    return {r[0] for r in rows}


@pytest.mark.parametrize("artifact,table_name", sorted(INTERMEDIATE.items()))
def test_published_schema_covers_intermediate_columns(artifact, table_name):
    """Every column a build script produces must exist in the published schema."""
    path = DIST / artifact
    if not path.exists():
        pytest.skip(f"dist/{artifact} not present (run scripts/build_all.py)")

    table = next(t for t in TABLES if t.name == table_name)
    declared = {c.name for c in table.columns}
    produced = _columns(path)

    dropped = produced - declared
    assert not dropped, (
        f"{artifact} produces column(s) {sorted(dropped)} that schema.py does not "
        f"declare on table '{table_name}'. build_db.py projects onto the declared "
        f"columns, so these would be silently discarded from the published database. "
        f"Add them to schema.py or remove them from the build script."
    )


def test_defect_verified_survives_into_published_curves():
    """The hurricane defect verification must reach users, not just the build dir."""
    published = DIST / "curves.parquet"
    if not published.exists():
        pytest.skip("dist/curves.parquet not present")
    if not (DIST / "curves_hu.parquet").exists():
        pytest.skip("hurricane not built")

    assert "defect_verified" in _columns(published), (
        "defect_verified is missing from the published curves table. The independent "
        "verification of FEMA's disclosed defect is documented in "
        "docs/hurricane_defect.md and must be queryable."
    )

    con = duckdb.connect()
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{published}') "
        f"WHERE defect_verified = 'identical_to_1_story'"
    ).fetchone()[0]
    con.close()
    assert n == 15200, (
        f"expected 15,200 curves verified identical to their 1-story counterpart, "
        f"found {n:,}. See docs/hurricane_defect.md."
    )
