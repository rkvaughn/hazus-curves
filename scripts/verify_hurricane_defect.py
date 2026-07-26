#!/usr/bin/env python3
"""Independently verify FEMA's disclosed multi-family hurricane curve defect.

FEMA's Hazus 7.1 release notes (RSA-21186) state that in Hazus 6.1 and 7.0 the 2- and
3-story multi-family wind damage functions "had been inadvertently overwritten with a
copy of the 1-story multi-family building damage functions."

This script does not take that on faith. It compares every 2-/3-story curve against the
1-story curve with *identical* building characteristics, terrain, and loss class, and
records which ones are byte-identical. The result is written back to
``dist/curves_hu.parquet`` as a ``defect_verified`` column and summarised in
``docs/hurricane_defect.md``.

Two distinct pieces of information are kept separate on purpose:

  defect_flag      FEMA disclosed that this building-type family is affected.
  defect_verified  We measured this specific curve to be identical to its 1-story
                   counterpart. Empirical, reproducible from the published data.

A curve that is flagged but not verified is not thereby "clean" -- FEMA also reported
that mitigated variants lacked correct data in a different way. Absence of evidence is
recorded as such, not as absence of the defect.
"""

import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
DOCS = REPO / "docs"

FAMILIES = ("WMUH", "MMUH")


def main() -> int:
    curves = DIST / "curves_hu.parquet"
    points = DIST / "curve_points_hu.parquet"
    if not curves.exists() or not points.exists():
        print("run scripts/build_hurricane.py first", file=sys.stderr)
        return 1

    con = duckdb.connect()
    con.execute(f"CREATE VIEW cur AS SELECT * FROM read_parquet('{curves}')")
    con.execute(f"CREATE VIEW pts AS SELECT * FROM read_parquet('{points}')")

    fam_filter = " OR ".join(
        f"c.building_type LIKE '{f}%'" for f in FAMILIES
    )

    con.execute(f"""
        CREATE TABLE sig AS
        SELECT c.curve_id,
               c.building_type,
               substr(c.building_type, 1, 4)                      AS family,
               right(c.building_type, 1)                          AS stories,
               c.description                                      AS chars,
               c.damage_type,
               regexp_extract(c.curve_id, 't([0-9]+)$', 1)        AS terrain,
               list(p.y ORDER BY p.x)                             AS y
        FROM cur c JOIN pts p USING(curve_id)
        WHERE {fam_filter}
        GROUP BY ALL
    """)

    # A multi-story curve is "verified duplicate" when a 1-story curve exists with the
    # same family, characteristics, terrain and loss class, and identical values.
    con.execute("""
        CREATE TABLE verdict AS
        SELECT m.curve_id,
               max(CASE WHEN m.y = o.y THEN 1 ELSE 0 END) = 1 AS is_duplicate,
               count(o.curve_id) > 0                          AS had_counterpart
        FROM sig m
        LEFT JOIN sig o
          ON o.family = m.family AND o.stories = '1'
         AND o.chars = m.chars AND o.terrain = m.terrain
         AND o.damage_type = m.damage_type
        WHERE m.stories IN ('2', '3')
        GROUP BY m.curve_id
    """)

    summary = con.execute("""
        SELECT s.building_type,
               count(*)                                   AS n_curves,
               sum(CASE WHEN v.is_duplicate THEN 1 ELSE 0 END) AS n_duplicate,
               sum(CASE WHEN v.had_counterpart THEN 0 ELSE 1 END) AS n_no_counterpart
        FROM verdict v JOIN sig s USING(curve_id)
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    out = DIST / "curves_hu_flagged.parquet"
    con.execute(f"""
        COPY (
          SELECT c.*,
                 CASE WHEN v.is_duplicate THEN 'identical_to_1_story'
                      WHEN v.curve_id IS NOT NULL THEN 'differs_from_1_story'
                      ELSE NULL END AS defect_verified
          FROM cur c LEFT JOIN verdict v USING(curve_id)
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    out.replace(curves)

    total = sum(r[1] for r in summary)
    dup = sum(r[2] for r in summary)

    lines = [
        "# Hurricane multi-family curve defect — independent verification",
        "",
        "FEMA's Hazus 7.1 release notes (RSA-21186) disclose that in Hazus 6.1 and 7.0",
        "the 2- and 3-story multi-family wind damage functions were inadvertently",
        "overwritten with copies of the 1-story functions.",
        "",
        "This project verified that claim directly against the Hazus 6.1 data it",
        "publishes, by comparing each 2-/3-story curve with the 1-story curve having",
        "identical building characteristics, terrain, and loss class.",
        "",
        "## Result",
        "",
        f"**{dup:,} of {total:,}** 2-/3-story multi-family curves ",
        f"({100 * dup / total:.1f}%) are byte-identical to their 1-story counterpart.",
        "The defect is real and measurable in the published data.",
        "",
        "| Building type | Curves | Identical to 1-story | Share |",
        "|---|---:|---:|---:|",
    ]
    for bt, n, d, _ in summary:
        lines.append(f"| {bt} | {n:,} | {d:,} | {100 * d / n:.1f}% |")
    lines += [
        "",
        "## How this is represented in the data",
        "",
        "| Column | Meaning |",
        "|---|---|",
        "| `defect_flag` | FEMA disclosed that this building-type family is affected. |",
        "| `defect_verified` | `identical_to_1_story` — measured here to be a duplicate. "
        "`differs_from_1_story` — not a duplicate. |",
        "",
        "`differs_from_1_story` does **not** mean the curve is correct. FEMA also",
        "reported that mitigated variants (with shutters, or stronger roof deck",
        "attachment) lacked correct data in a different way, and that its 7.1 fix",
        "*synthesised* replacements for those rather than recovering originals.",
        "Absence of evidence is recorded as absence of evidence, not as absence of the",
        "defect.",
        "",
        "## Why these curves are published rather than withheld",
        "",
        "A flagged curve is more useful than a missing one, and the flag is itself",
        "information that no other open dataset carries. Hazus 7.1+ contains the",
        "corrected functions but is not publicly extractable without Windows, ArcGIS",
        "Pro, and SQL Server.",
        "",
        "Reproduce with `python scripts/verify_hurricane_defect.py`.",
        "",
    ]
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "hurricane_defect.md").write_text("\n".join(lines))

    print(f"  {dup:,}/{total:,} multi-story curves identical to 1-story "
          f"({100 * dup / total:.1f}%)")
    for bt, n, d, nc in summary:
        print(f"    {bt}: {d:,}/{n:,} duplicate"
              + (f"  ({nc} without counterpart)" if nc else ""))
    print(f"\n  wrote docs/hurricane_defect.md and updated {curves.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
