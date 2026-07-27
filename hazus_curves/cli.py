"""``hazus-curves`` command line interface.

    hazus-curves install                          # flood -> ~/.hazus_curves/
    hazus-curves install --perils fl,hu           # add hurricane wind
    hazus-curves install --target duckdb:///my.db
    hazus-curves install --target postgresql://user@host/db
    hazus-curves info
    hazus-curves query "SELECT * FROM curves LIMIT 5"

The default target is a local SQLite file, which needs no server and no configuration.
Other engines are loaded through SQLAlchemy from the same Parquet artifacts, using DDL
generated from the single schema definition in ``hazus_curves.schema``.
"""

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

from .reader import DEFAULT_DB_NAME, connect, default_db_path
from .schema import TABLES, ddl

# Prebuilt artifacts. Overridable with --from for local builds or a private mirror.
# Also referenced by site/index.html (the header repo link). Keep both in step if the
# repository is renamed or moved.
REPO_URL = "https://github.com/rkvaughn/hazus-curves"
RELEASE_BASE = f"{REPO_URL}/releases/latest/download/"

PERIL_NAMES = {"fl": "flood", "hu": "hurricane wind"}


def _repo_dist() -> Path:
    """dist/ inside a source checkout, if we are running from one."""
    return Path(__file__).resolve().parent.parent / "dist"


def cmd_install(args) -> int:
    perils = [p.strip() for p in args.perils.split(",") if p.strip()]
    unknown = [p for p in perils if p not in PERIL_NAMES]
    if unknown:
        print(f"unknown peril(s): {unknown}; known: {sorted(PERIL_NAMES)}",
              file=sys.stderr)
        return 2

    dest = Path(args.output) if args.output else default_db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)

    source = Path(args.source) if args.source else _repo_dist()
    local_db = source / DEFAULT_DB_NAME

    if args.target and not args.target.startswith("sqlite"):
        return _load_remote_engine(args.target, source, perils)

    if local_db.exists():
        shutil.copy2(local_db, dest)
        print(f"installed from {local_db}")
    else:
        url = RELEASE_BASE + DEFAULT_DB_NAME
        print(f"downloading {url}")
        try:
            with urllib.request.urlopen(url) as resp, dest.open("wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception as exc:  # noqa: BLE001 - report plainly, do not mask
            print(f"download failed: {exc}\n\n"
                  f"If you have a source checkout, build locally instead:\n"
                  f"    python scripts/fetch.py && python scripts/build_flood.py "
                  f"&& python scripts/build_db.py", file=sys.stderr)
            return 1

    con = connect(dest)
    n = con.execute("SELECT count(*) FROM curves").fetchone()[0]
    pts = con.execute("SELECT count(*) FROM curve_points").fetchone()[0]
    con.close()
    print(f"{dest}\n  {n:,} curves, {pts:,} points")
    print(f"\nTry:  hazus-curves query \"SELECT * FROM curves LIMIT 5\"")
    return 0


def _load_remote_engine(target: str, source: Path, perils) -> int:
    try:
        import pandas as pd
        from sqlalchemy import create_engine, text
    except ImportError:
        print("this target needs: pip install 'hazus-curves[sql]'", file=sys.stderr)
        return 1

    engine_name = target.split(":", 1)[0].split("+", 1)[0]
    alias = {"postgres": "postgresql"}.get(engine_name, engine_name)
    engine = create_engine(target)
    print(f"loading into {alias}")

    with engine.begin() as con:
        for statement in ddl(alias).split(";\n"):
            if statement.strip():
                con.execute(text(statement))
        for t in TABLES:
            pq = source / f"{t.name}.parquet"
            if not pq.exists():
                print(f"  skip {t.name} (no {pq.name})")
                continue
            df = pd.read_parquet(pq)
            df.to_sql(t.name, con, if_exists="append", index=False,
                      method="multi", chunksize=5000)
            print(f"  {t.name:<20} {len(df):>10,} rows")
    print("done")
    return 0


def cmd_info(args) -> int:
    con = connect(Path(args.db) if args.db else None)
    print("perils:")
    for r in con.execute("""SELECT peril, hazus_version, damage_type, count(*) n
                            FROM curves GROUP BY 1,2,3 ORDER BY 1,2,3"""):
        print(f"  {r['peril']}  {r['hazus_version']:<5} {r['damage_type']:<24}"
              f" {r['n']:>8,}")
    flagged = con.execute(
        "SELECT count(*) FROM curves WHERE defect_flag IS NOT NULL").fetchone()[0]
    if flagged:
        print(f"\n{flagged:,} curves carry a FEMA-disclosed defect flag "
              f"(see docs/hurricane_defect.md)")
    print("\nprovenance:")
    for r in con.execute("SELECT source_file, hazus_version, bytes FROM provenance"
                         " ORDER BY source_file"):
        print(f"  {r['source_file']:<45} {r['hazus_version']:<5} "
              f"{r['bytes']:>12,} B")
    con.close()
    return 0


def cmd_query(args) -> int:
    con = connect(Path(args.db) if args.db else None)
    cur = con.execute(args.sql)
    rows = cur.fetchall()
    if not rows:
        print("(no rows)")
        return 0
    cols = rows[0].keys()
    widths = [max(len(c), max(len(str(r[c])) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))
    con.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hazus-curves", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", help="download and install the curve database")
    p.add_argument("--perils", default="fl", help="comma-separated: fl,hu")
    p.add_argument("--target", help="SQLAlchemy URL; default is local SQLite")
    p.add_argument("--output", help="SQLite file path")
    p.add_argument("--source", help="directory of prebuilt artifacts")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("info", help="describe the installed database")
    p.add_argument("--db")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("query", help="run a read-only SQL query")
    p.add_argument("sql")
    p.add_argument("--db")
    p.set_defaults(func=cmd_query)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
