"""Orchestration: extract -> validate -> transform -> validate -> load, with run logging.

    python -m etl.pipeline --data-dir data/ipl_csv2 --db-url postgresql+psycopg://user:pw@localhost/ipl
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine

from . import extract, load, schema, transform, validate

log = logging.getLogger("etl")


@dataclass
class RunSummary:
    run_id: int
    status: str
    match_files: int = 0
    deliveries: int = 0
    matches: int = 0
    issues: list[validate.Issue] = field(default_factory=list)


def run_pipeline(data_dir: str | Path, db_url: str, dry_run: bool = False) -> RunSummary:
    engine = create_engine(db_url)
    schema.metadata.create_all(engine)
    run_id = load.start_run(engine)
    summary = RunSummary(run_id=run_id, status="RUNNING")
    counts: dict = {}
    try:
        log.info("run %s: extracting from %s", run_id, data_dir)
        files = extract.discover(data_dir)
        balls = extract.read_balls(files.match_files)
        info = extract.read_info(files.info_files)
        counts.update(match_files=len(files.match_files), skipped_files=len(files.skipped),
                      matches_extracted=len(info), deliveries_extracted=len(balls))
        summary.match_files = len(files.match_files)

        if not files.match_files:
            summary.issues.append(validate.Issue("no_match_files", validate.ERROR,
                                                 f"No <id>.csv files found in {data_dir}", 0))
        else:
            summary.issues += validate.validate_raw(balls, info, files.skipped)

        if not validate.has_errors(summary.issues):
            matches = transform.clean_matches(info)
            deliveries = transform.clean_deliveries(balls)
            summary.issues += validate.validate_clean(matches, deliveries)

        if validate.has_errors(summary.issues):
            summary.status = "FAILED_VALIDATION"
            load.finish_run(engine, run_id, summary.status, summary.issues, **counts,
                            message="Validation errors; nothing was loaded")
            return summary

        if dry_run:
            summary.status = "DRY_RUN"
            counts.update(matches_loaded=0, deliveries_loaded=0)
        else:
            loaded_matches, loaded_deliveries = load.load_tables(engine, matches, deliveries)
            summary.status = "SUCCESS"
            counts.update(matches_loaded=loaded_matches, deliveries_loaded=loaded_deliveries)
        summary.matches, summary.deliveries = len(matches), len(deliveries)
        load.finish_run(engine, run_id, summary.status, summary.issues, **counts)
        return summary
    except Exception as exc:
        log.exception("run %s failed", run_id)
        load.finish_run(engine, run_id, "FAILED_ERROR", summary.issues, **counts, message=str(exc)[:500])
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IPL ball-by-ball ETL pipeline")
    parser.add_argument("--data-dir", required=True, help="Folder with the Cricsheet IPL CSV files")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL", "sqlite:///ipl.db"),
                        help="SQLAlchemy URL (default: $DATABASE_URL, else sqlite:///ipl.db)")
    parser.add_argument("--dry-run", action="store_true", help="Extract and validate only; load nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    summary = run_pipeline(args.data_dir, args.db_url, dry_run=args.dry_run)

    print(f"\nRun {summary.run_id}: {summary.status}")
    print(f"  match files: {summary.match_files} | matches: {summary.matches} | deliveries: {summary.deliveries}")
    for issue in summary.issues:
        print(f"  [{issue.severity}] {issue.check}: {issue.detail} ({issue.count})")
    return 1 if summary.status.startswith("FAILED") else 0


if __name__ == "__main__":
    sys.exit(main())
