"""Load: write cleaned tables to the database and keep an audit trail."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import bindparam, delete, func, insert, select, update
from sqlalchemy.engine import Engine

from . import schema
from .validate import Issue

CHUNK = 20_000


def _records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of dicts with NaN/NaT turned into None."""
    cleaned = frame.astype(object).where(pd.notna(frame), None)
    return cleaned.to_dict("records")


def _insert_chunks(conn, table, frame: pd.DataFrame) -> None:
    records = _records(frame)
    for start in range(0, len(records), CHUNK):
        conn.execute(insert(table), records[start:start + CHUNK])


def load_tables(engine: Engine, matches: pd.DataFrame, deliveries: pd.DataFrame) -> tuple[int, int]:
    """Replace the rows for the matches in this batch, in one transaction.

    Re-running on the same files gives the same database (idempotent), and new
    seasons can be added without touching existing matches. If the row counts in
    the database do not match what was sent, the transaction is rolled back.
    """
    match_ids = [int(m) for m in matches["match_id"]]
    with engine.begin() as conn:
        for table in (schema.deliveries, schema.matches):
            conn.execute(delete(table).where(table.c.match_id.in_(bindparam("ids", expanding=True))),
                         {"ids": match_ids})
        _insert_chunks(conn, schema.matches, matches)
        _insert_chunks(conn, schema.deliveries, deliveries)

        db_matches = conn.execute(select(func.count()).select_from(schema.matches)
                                  .where(schema.matches.c.match_id.in_(match_ids))).scalar_one()
        db_deliveries = conn.execute(select(func.count()).select_from(schema.deliveries)
                                     .where(schema.deliveries.c.match_id.in_(match_ids))).scalar_one()
        if db_matches != len(matches) or db_deliveries != len(deliveries):
            raise RuntimeError(
                f"Reconciliation failed: sent {len(matches)} matches / {len(deliveries)} deliveries, "
                f"database has {db_matches} / {db_deliveries}")
    return db_matches, db_deliveries


def start_run(engine: Engine) -> int:
    with engine.begin() as conn:
        result = conn.execute(insert(schema.etl_run_log).values(
            status="RUNNING", started_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        return int(result.inserted_primary_key[0])


def finish_run(engine: Engine, run_id: int, status: str, issues: list[Issue], **counts) -> None:
    """Record the outcome and every data-quality issue, in its own transaction so a
    failed load still leaves an audit row behind."""
    errors = sum(1 for i in issues if i.severity == "ERROR")
    warnings = sum(1 for i in issues if i.severity == "WARNING")
    with engine.begin() as conn:
        conn.execute(update(schema.etl_run_log).where(schema.etl_run_log.c.run_id == run_id).values(
            status=status, finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            errors=errors, warnings=warnings, **counts))
        if issues:
            conn.execute(insert(schema.dq_issue), [
                {"run_id": run_id, "check_name": i.check, "severity": i.severity,
                 "detail": i.detail, "affected_count": i.count} for i in issues])
