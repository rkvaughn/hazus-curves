"""Building type names must be sourced, complete, and never invented.

The hurricane workbook identifies building types by bare code only -- no sheet in it
carries a natural-language name. The names come from Table C-1 of the Hazus Hurricane
Technical Manual, parsed by scripts/extract_building_types.py.

The failure mode these tests exist to prevent is a plausible-looking description that
nobody sourced. "WSF1 = Wood Single Family, 1 Story" is easy to write from memory and
impossible to audit after the fact.
"""

import csv
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DATA, DIST, RAW = REPO / "data", REPO / "dist", REPO / "raw"
sys.path.insert(0, str(REPO))

BT_CSV = DATA / "dim_building_type.csv"

# Hazus defines 39 hurricane specific building types; the manual's Table C-1 lists
# exactly that many, and the data contains exactly that many distinct codes.
EXPECTED_COUNT = 39


def _rows():
    if not BT_CSV.exists():
        pytest.skip("data/dim_building_type.csv not present (run build_hurricane.py)")
    with BT_CSV.open() as fh:
        return list(csv.DictReader(fh))


def test_all_building_types_present():
    rows = _rows()
    assert len(rows) == EXPECTED_COUNT, (
        f"expected {EXPECTED_COUNT} specific building types, found {len(rows)}"
    )
    assert len({r["building_type"] for r in rows}) == len(rows), "duplicate codes"


def test_every_building_type_has_a_description():
    rows = _rows()
    missing = sorted(r["building_type"] for r in rows if not (r.get("description") or "").strip())
    if missing:
        pytest.fail(
            f"{len(missing)} building type(s) have no description: {missing}\n"
            f"Run: python scripts/fetch.py --docs && "
            f"python scripts/extract_building_types.py\n"
            f"Do NOT hand-write these -- they must come from the Technical Manual."
        )


def test_descriptions_match_the_technical_manual_verbatim():
    """Re-parse the manual and require exact agreement with what we published.

    This is the test that makes the descriptions auditable: if anyone edits the CSV by
    hand, or an extraction bug lets a wrong string through, the published value stops
    matching its cited source and this fails.
    """
    manual = RAW / "fema_rsl_hazus-7-hutm_06272025_0.pdf"
    if not manual.exists():
        pytest.skip("Hurricane Technical Manual not fetched (scripts/fetch.py --docs)")
    pytest.importorskip("pypdf")

    from scripts.extract_building_types import extract  # noqa: PLC0415

    sourced = extract(manual)
    published = {r["building_type"]: (r.get("description") or "").strip()
                 for r in _rows()}

    mismatched = {
        code: (desc, sourced.get(code))
        for code, desc in published.items()
        if desc and sourced.get(code) != desc
    }
    assert not mismatched, (
        "published description(s) do not match the Technical Manual:\n" +
        "\n".join(f"  {c}: published {p!r} != manual {m!r}"
                  for c, (p, m) in sorted(mismatched.items()))
    )


def test_no_description_leaks_the_table_c2_statistics_rows():
    """Table C-2 reuses the same row labels with statistics; none may leak through."""
    import re
    for row in _rows():
        desc = (row.get("description") or "").strip()
        assert not re.match(r"^\d{1,2}-", desc), (
            f"{row['building_type']} description {desc!r} looks like a Table C-2 "
            f"WBC statistics row, not a building type name"
        )


def test_published_parquet_carries_descriptions():
    pq = DIST / "dim_building_type.parquet"
    if not pq.exists():
        pytest.skip("dist/dim_building_type.parquet not present")
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    n_missing = con.execute(
        f"SELECT count(*) FROM read_parquet('{pq}') "
        f"WHERE description IS NULL OR trim(description) = ''"
    ).fetchone()[0]
    con.close()
    assert n_missing == 0, (
        f"{n_missing} building types reach the published database with no description"
    )
