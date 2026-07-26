"""Regression tests for the geographic scoping audit (docs/audit_geographic_mapping.md).

All three bugs these cover failed *silently* — they returned a plausible curve computed
over the wrong population rather than erroring. The tests therefore pin absolute counts,
not just "returns something".
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
sys.path.insert(0, str(REPO))

duckdb = pytest.importorskip("duckdb")


@pytest.fixture(scope="module")
def con():
    need = ["curves.parquet", "curve_attributes.parquet", "dim_geographic_case.parquet",
            "assignment_rules.parquet", "curve_zone_applicability.parquet"]
    missing = [n for n in need if not (DIST / n).exists()]
    if missing:
        pytest.skip(f"missing artifacts: {missing} (run scripts/build_all.py)")
    c = duckdb.connect()
    c.execute(f"CREATE VIEW cu AS SELECT * FROM read_parquet('{DIST}/curves.parquet')")
    c.execute(f"CREATE VIEW attr AS SELECT * FROM read_parquet('{DIST}/curve_attributes.parquet')")
    c.execute(f"CREATE VIEW dg AS SELECT * FROM read_parquet('{DIST}/dim_geographic_case.parquet')")
    c.execute(f"CREATE VIEW ar AS SELECT * FROM read_parquet('{DIST}/assignment_rules.parquet')")
    c.execute(f"CREATE VIEW cza AS SELECT * FROM read_parquet('{DIST}/curve_zone_applicability.parquet')")
    yield c
    c.close()


def _has_hurricane(con):
    return con.execute("SELECT count(*) FROM cu WHERE peril='hu'").fetchone()[0] > 0


# ── Finding 1: geographic_case is set-valued ────────────────────────────────────

EXPECTED_CASE_TERRITORIES = {
    ("ContinentalUS", "CONUS"),
    ("Hawaii", "Hawaii"),
    ("ContUS+Hawaii", "CONUS"),
    ("ContUS+Hawaii", "Hawaii"),
    ("ContUS+Caribbean", "CONUS"),
    ("ContUS+Caribbean", "Caribbean"),
}


def test_geographic_case_decomposition_matches_hazus(con):
    rows = set(con.execute("SELECT case_name, territory FROM dg").fetchall())
    assert rows == EXPECTED_CASE_TERRITORIES, (
        "geographic case -> territory decomposition changed. It must follow Hazus's "
        "own CaseDescription strings, e.g. 'Used in Continental and Hawaii'."
    )


def test_multi_territory_cases_are_not_collapsed(con):
    """The whole point: some cases must map to more than one territory."""
    multi = con.execute(
        "SELECT case_name, count(*) n FROM dg GROUP BY 1 HAVING count(*) > 1"
    ).fetchall()
    assert {c for c, _ in multi} == {"ContUS+Hawaii", "ContUS+Caribbean"}


@pytest.mark.parametrize("territory,expected", [
    ("Hawaii", 19980),
    ("CONUS", 28380),
    ("Caribbean", 5200),
])
def test_territory_membership_beats_case_equality(con, territory, expected):
    """Pin the corrected counts for damage_severe.

    Equality filtering returned 1,600 for Hawaii and 4,800 for CONUS. If these numbers
    regress toward those, the set-valued attribute is being compared with = again.
    """
    if not _has_hurricane(con):
        pytest.skip("hurricane not built")
    n = con.execute(f"""
        SELECT count(*) FROM cu c
        WHERE c.peril='hu' AND c.damage_type='damage_severe'
          AND EXISTS (SELECT 1 FROM attr g JOIN dg t ON t.case_name = g.value
                      WHERE g.curve_id=c.curve_id AND g.key='geographic_case'
                        AND t.territory='{territory}')
    """).fetchone()[0]
    assert n == expected


def test_hawaii_includes_contus_hawaii_curves(con):
    """The specific exclusion that made the bug severe."""
    if not _has_hurricane(con):
        pytest.skip("hurricane not built")
    n = con.execute("""
        SELECT count(*) FROM cu c
        WHERE c.peril='hu'
          AND EXISTS (SELECT 1 FROM attr g JOIN dg t ON t.case_name=g.value
                      WHERE g.curve_id=c.curve_id AND g.key='geographic_case'
                        AND t.territory='Hawaii')
          AND EXISTS (SELECT 1 FROM attr g2 WHERE g2.curve_id=c.curve_id
                        AND g2.key='geographic_case' AND g2.value='ContUS+Hawaii')
    """).fetchone()[0]
    assert n == 165420, (
        "ContUS+Hawaii curves must be reachable from a Hawaii selection; they apply "
        "there by Hazus's own description."
    )


# ── Finding 2: zone filtering dropped every Hazus 4.0 curve ─────────────────────

@pytest.mark.parametrize("zone", ["Riverine", "CoastalA", "CoastalV"])
def test_zone_filter_returns_hazus_4_0_curves(con, zone):
    n = con.execute(f"""
        SELECT count(DISTINCT c.curve_id) FROM cu c
        JOIN cza z ON z.curve_id = c.curve_id
        WHERE c.peril='fl' AND c.hazus_version='4.0' AND z.flood_zone='{zone}'
    """).fetchone()[0]
    assert n > 0, (
        f"zone={zone} returns no Hazus 4.0 curves. This was the original bug: the "
        f"filter joined assignment_rules, which held 6.1 rows only."
    )


def test_assignment_rules_cover_both_vintages(con):
    versions = {r[0] for r in con.execute(
        "SELECT DISTINCT hazus_version FROM ar").fetchall()}
    assert versions == {"4.0", "6.1"}, (
        f"assignment_rules covers {versions}; both published vintages are required."
    )


# ── Finding 3: zone filter narrowed the library to defaults ─────────────────────

def test_zone_applicability_is_broader_than_default_assignments(con):
    """curve_zone_applicability must not simply mirror the default-selection table."""
    applicable = con.execute(
        "SELECT count(DISTINCT curve_id) FROM cza").fetchone()[0]
    defaults = con.execute(
        "SELECT count(DISTINCT curve_id) FROM ar").fetchone()[0]
    assert applicable >= defaults, (
        f"zone applicability ({applicable}) is narrower than default assignments "
        f"({defaults}); the filter would be excluding curves Hazus flags as usable."
    )


def test_unzoned_search_reaches_the_whole_library(con):
    """With no zone selected the full flood library must be reachable."""
    total = con.execute("SELECT count(*) FROM cu WHERE peril='fl'").fetchone()[0]
    assert total == 3046


def test_zone_applicability_has_no_dangling_curves(con):
    n = con.execute("""
        SELECT count(*) FROM cza z
        LEFT JOIN cu c ON c.curve_id = z.curve_id
        WHERE c.curve_id IS NULL
    """).fetchone()[0]
    assert n == 0


# ── Finding 4: the Hazus 7.0 coastal rule must actually be in the data ──────────

def test_hazus_7_0_coastal_rule_is_recorded(con):
    """docs/version_changes.md promises this rule lives in the data. It must."""
    n = con.execute("""
        SELECT count(*) FROM ar
        WHERE flood_zone IN ('CoastalA','CoastalV') AND notes IS NOT NULL
    """).fetchone()[0]
    assert n > 0, "no coastal rule carries the Hazus 7.0 depth-limited supersession note"

    sample = con.execute("""
        SELECT notes FROM ar WHERE notes IS NOT NULL LIMIT 1
    """).fetchone()[0]
    for token in ("6 ft", "3 ft", "7.0"):
        assert token in sample, f"note does not mention {token!r}: {sample!r}"


def test_riverine_rules_are_not_annotated_with_the_coastal_rule(con):
    """The 7.0 change is about coastal assignment; riverine notes would be wrong."""
    n = con.execute("""
        SELECT count(*) FROM ar WHERE flood_zone='Riverine' AND notes IS NOT NULL
    """).fetchone()[0]
    assert n == 0
