#!/usr/bin/env python3
"""Extract Specific Building Type descriptions from the Hazus Hurricane Technical Manual.

The wind workbook identifies building types by bare code (``WSF1``, ``MMUH3``) and
contains no natural-language names for them anywhere -- every sheet was checked. The
names live in the Technical Manual, Appendix C, Table C-1 "List of SBT Abbreviations".

This parses that table out of the PDF rather than transcribing it, and then asserts the
extracted set is exactly the set of codes present in the data. If the manual and the
data disagree, the script fails instead of publishing a partial or invented mapping.

    python scripts/fetch.py --docs
    python scripts/extract_building_types.py

Writes data/dim_building_type.csv.
"""

import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW, DATA, DIST = REPO / "raw", REPO / "data", REPO / "dist"

MANUAL = "fema_rsl_hazus-7-hutm_06272025_0.pdf"
TABLE_HEADER = "SBT # and Name"

# Table C-1: "01_WSF1 Single Family Homes, 1 Story - Wood"
ROW = re.compile(r"^\s*(\d{2})_([A-Za-z0-9]+)\s+(\S.*?)\s*$")

# Table C-2 immediately follows and reuses the same "NN_SBT" row labels, but its
# description column is a WBC name prefixed with its own number ("01-Roof Shape Hip")
# followed by statistics. Both tables also repeat the same running page header, so the
# header alone cannot tell them apart -- this prefix can.
C2_ROW = re.compile(r"^\d{1,2}-")


def extract(pdf_path: Path) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    found, in_table = {}, False
    for page in reader.pages:
        text = page.extract_text() or ""
        if TABLE_HEADER in text:
            in_table = True
        elif not in_table:
            continue

        matched_here = False
        for line in text.split("\n"):
            m = ROW.match(line)
            if not m:
                continue
            _num, code, description = m.groups()
            description = " ".join(description.split())
            if C2_ROW.match(description):
                # Reached Table C-2. Table C-1 is complete.
                return found
            if code in found and found[code] != description:
                raise ValueError(
                    f"{code} appears twice with different descriptions:\n"
                    f"  {found[code]!r}\n  {description!r}"
                )
            found[code] = description
            matched_here = True

        # The table runs over consecutive pages; the first page after it with no rows
        # ends it. Stops us walking into unrelated numbered content later on.
        if in_table and found and not matched_here:
            break
    return found


def data_codes() -> set:
    csv_path = DATA / "dim_building_type.csv"
    parquet = DIST / "curves_hu.parquet"
    if parquet.exists():
        import duckdb
        con = duckdb.connect()
        rows = con.execute(
            f"SELECT DISTINCT building_type FROM read_parquet('{parquet}') "
            f"WHERE building_type IS NOT NULL"
        ).fetchall()
        con.close()
        return {r[0] for r in rows}
    if csv_path.exists():
        with csv_path.open() as fh:
            return {r["building_type"] for r in csv.DictReader(fh)
                    if r.get("building_type")}
    raise SystemExit("no hurricane build found; run scripts/build_hurricane.py first")


def main() -> int:
    pdf = RAW / MANUAL
    if not pdf.exists():
        print(f"missing {pdf.relative_to(REPO)}\n"
              f"run: python scripts/fetch.py --docs", file=sys.stderr)
        return 1

    descriptions = extract(pdf)
    print(f"  parsed {len(descriptions)} SBT descriptions from {MANUAL}")

    present = data_codes()
    missing = present - set(descriptions)
    extra = set(descriptions) - present

    if missing:
        print(f"\nno description found for building type(s) in the data: "
              f"{sorted(missing)}\n"
              f"Refusing to write a partial mapping -- a missing name must stay "
              f"missing rather than be guessed.", file=sys.stderr)
        return 1
    if extra:
        # Not fatal: the manual documents Hazus 7.0, the data is 6.1.
        print(f"  note: manual documents {len(extra)} type(s) absent from this data: "
              f"{sorted(extra)}")

    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "dim_building_type.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["building_type", "description"])
        for code in sorted(present):
            w.writerow([code, descriptions[code]])

    print(f"  all {len(present)} building types in the data have a sourced description")
    print(f"  wrote {out.relative_to(REPO)}")
    for code in sorted(present)[:5]:
        print(f"    {code:<12} {descriptions[code]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
