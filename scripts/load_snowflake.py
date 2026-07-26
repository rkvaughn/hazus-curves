#!/usr/bin/env python3
"""Load the full curve database into Snowflake.

Credentials come from the environment only -- never from a file in this repo, and
never defaulted:

    export SNOWFLAKE_ACCOUNT=...      SNOWFLAKE_USER=...
    export SNOWFLAKE_PASSWORD=...     SNOWFLAKE_WAREHOUSE=...
    export SNOWFLAKE_DATABASE=...     SNOWFLAKE_SCHEMA=PUBLIC

    python scripts/load_snowflake.py --dry-run     # print the SQL, connect to nothing
    python scripts/load_snowflake.py

Uploads dist/*.parquet to an internal stage and COPY INTOs each table. Idempotent:
tables are created IF NOT EXISTS and truncated before load, so re-running replaces
rather than duplicating.

NOTE: this script has not been executed against a live Snowflake warehouse. The DDL and
statement construction are unit-tested offline and --dry-run works, but the load path
itself is unverified. Treat the first run as a test.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hazus_curves.schema import TABLES, ddl

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"

REQUIRED_ENV = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
                "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE"]

STAGE = "HAZUS_CURVES_STAGE"


def statements(tables=None):
    """Every SQL statement the load will run, in order."""
    out = [f"CREATE STAGE IF NOT EXISTS {STAGE} "
           f"FILE_FORMAT = (TYPE = PARQUET);"]
    out += [s for s in ddl("snowflake", tables).split(";\n") if s.strip()]
    for t in (tables or TABLES):
        cols = ", ".join(c.name for c in t.columns)
        select = ", ".join(
            f"$1:{c.name}::{_sf_type(c)}" for c in t.columns
        )
        out.append(f"TRUNCATE TABLE IF EXISTS {t.name};")
        out.append(
            f"COPY INTO {t.name} ({cols})\n"
            f"  FROM (SELECT {select} FROM @{STAGE}/{t.name}.parquet)\n"
            f"  FILE_FORMAT = (TYPE = PARQUET)\n"
            f"  ON_ERROR = ABORT_STATEMENT;"
        )
    return out


def _sf_type(column):
    from hazus_curves.schema import TYPE_MAP
    return TYPE_MAP["snowflake"][column.type]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the SQL and exit without connecting")
    args = ap.parse_args()

    if args.dry_run:
        for s in statements():
            print(s if s.rstrip().endswith(";") else s + ";")
            print()
        return 0

    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"missing environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        import snowflake.connector
    except ImportError:
        print("pip install snowflake-connector-python", file=sys.stderr)
        return 1

    parquets = [DIST / f"{t.name}.parquet" for t in TABLES]
    absent = [p.name for p in parquets if not p.exists()]
    if absent:
        print(f"missing artifacts in dist/: {absent}\n"
              f"run: python scripts/build_db.py --perils fl,hu", file=sys.stderr)
        return 1

    con = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC"),
    )
    cur = con.cursor()
    try:
        cur.execute(f"CREATE STAGE IF NOT EXISTS {STAGE} "
                    f"FILE_FORMAT = (TYPE = PARQUET)")
        for p in parquets:
            print(f"  staging {p.name}")
            cur.execute(f"PUT file://{p} @{STAGE} OVERWRITE = TRUE AUTO_COMPRESS = FALSE")
        for s in statements():
            if s.startswith("CREATE STAGE"):
                continue
            cur.execute(s.rstrip(";"))
        for t in TABLES:
            n = cur.execute(f"SELECT count(*) FROM {t.name}").fetchone()[0]
            print(f"  {t.name:<20} {n:>12,} rows")
    finally:
        cur.close()
        con.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
