import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from etl import extract, transform, validate
from etl.pipeline import run_pipeline
from tests.helpers import MATCHES, TOTAL_DELIVERIES, write_dataset


@pytest.fixture
def data_dir(tmp_path):
    return write_dataset(tmp_path / "data")


@pytest.fixture(params=["sqlite", "postgres"])
def db_url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run the PostgreSQL tests")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    return url


# ---------------------------------------------------------------- extract
def test_discover_separates_match_info_and_other_files(tmp_path):
    folder = write_dataset(tmp_path / "d", with_combined_file=True)
    (folder / "README.txt").write_text("not a csv")
    found = extract.discover(folder)
    assert len(found.match_files) == 3
    assert len(found.info_files) == 3
    assert [p.name for p in found.skipped] == ["all_matches.csv"]


def test_read_info_parses_teams_and_ignores_player_rows(data_dir):
    info = extract.read_info(extract.discover(data_dir).info_files)
    row = info[info.match_id == 1001].iloc[0]
    assert (row.team1, row.team2) == ("Delhi Daredevils", "Kings XI Punjab")
    assert row.winner_runs == "10"
    assert "player" not in info.columns


# -------------------------------------------------------------- transform
def test_transform_uses_match_date_for_season_and_renames_teams(data_dir):
    files = extract.discover(data_dir)
    matches = transform.clean_matches(extract.read_info(files.info_files))
    first = matches[matches.match_id == 1001].iloc[0]
    assert first.season == 2008                      # '2007/08' in the source
    assert first.team1 == "Delhi Capitals"
    assert first.team2 == "Punjab Kings"
    assert first.winner == "Delhi Capitals"
    assert first.winner_runs == 10


def test_transform_derives_over_and_legal_delivery_flags(data_dir):
    files = extract.discover(data_dir)
    deliveries = transform.clean_deliveries(extract.read_balls(files.match_files))
    assert len(deliveries) == TOTAL_DELIVERIES
    wide = deliveries[deliveries.wides == 1]
    assert (wide.is_legal_delivery == False).all()    # noqa: E712
    assert deliveries.over_number.max() == 0          # all test balls are in the first over
    assert deliveries.wides.dtype.kind == "i"         # blank wides -> 0


# --------------------------------------------------------------- validate
def test_clean_data_has_no_errors(data_dir):
    files = extract.discover(data_dir)
    issues = validate.validate_raw(extract.read_balls(files.match_files),
                                   extract.read_info(files.info_files), files.skipped)
    assert not validate.has_errors(issues)


def test_double_counted_match_is_an_error(data_dir):
    files = extract.discover(data_dir)
    balls = extract.read_balls(files.match_files)
    info = extract.read_info(files.info_files)
    dup = balls[balls.match_id == 1001].copy()
    dup["source_file"] = "all_matches.csv"
    issues = validate.validate_raw(pd.concat([balls, dup], ignore_index=True), info, [])
    assert "match_in_multiple_files" in {i.check for i in issues if i.severity == "ERROR"}


def test_too_many_deliveries_per_match_is_an_error(data_dir):
    files = extract.discover(data_dir)
    balls = extract.read_balls(files.match_files)
    info = extract.read_info(files.info_files)
    bloated = pd.concat([balls] + [balls[balls.match_id == 1002]] * 40, ignore_index=True)
    issues = validate.validate_raw(bloated, info, [])
    assert "too_many_deliveries_per_match" in {i.check for i in issues if i.severity == "ERROR"}


def test_missing_required_column_is_an_error(data_dir):
    files = extract.discover(data_dir)
    balls = extract.read_balls(files.match_files).drop(columns=["runs_off_bat"])
    issues = validate.validate_raw(balls, extract.read_info(files.info_files), [])
    assert [i.check for i in issues] == ["ball_columns_missing"]


def test_deliveries_without_match_info_is_an_error(data_dir):
    files = extract.discover(data_dir)
    balls = extract.read_balls(files.match_files)
    info = extract.read_info(files.info_files)
    issues = validate.validate_raw(balls, info[info.match_id != 1003], [])
    assert "deliveries_without_match_info" in {i.check for i in issues if i.severity == "ERROR"}


# --------------------------------------------------------------- pipeline
def counts(url):
    engine = create_engine(url)
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
                for t in ("matches", "deliveries", "etl_run_log", "dq_issue")}


def test_end_to_end_load_and_audit_trail(data_dir, db_url):
    summary = run_pipeline(data_dir, db_url)
    assert summary.status == "SUCCESS"
    c = counts(db_url)
    assert c["matches"] == len(MATCHES)
    assert c["deliveries"] == TOTAL_DELIVERIES
    with create_engine(db_url).connect() as conn:
        log = conn.execute(text("SELECT status, deliveries_extracted, deliveries_loaded, errors "
                                "FROM etl_run_log")).one()
        assert tuple(log) == ("SUCCESS", TOTAL_DELIVERIES, TOTAL_DELIVERIES, 0)
        dls = conn.execute(text("SELECT COUNT(*) FROM matches WHERE method IS NOT NULL")).scalar_one()
        assert dls == 1


def test_rerun_is_idempotent(data_dir, db_url):
    run_pipeline(data_dir, db_url)
    run_pipeline(data_dir, db_url)
    c = counts(db_url)
    assert (c["matches"], c["deliveries"]) == (len(MATCHES), TOTAL_DELIVERIES)  # no duplicates
    assert c["etl_run_log"] == 2                                                # both runs logged


def test_combined_file_is_skipped_so_nothing_is_double_counted(tmp_path, db_url):
    folder = write_dataset(tmp_path / "with_combined", with_combined_file=True)
    summary = run_pipeline(folder, db_url)
    assert summary.status == "SUCCESS"
    assert counts(db_url)["deliveries"] == TOTAL_DELIVERIES
    assert "non_match_files_skipped" in {i.check for i in summary.issues}


def test_failed_validation_loads_nothing_but_is_logged(data_dir, db_url):
    # corrupt one match file: a delivery count far above a real match
    path = data_dir / "1002.csv"
    body = path.read_text().splitlines()
    path.write_text("\n".join(body + body[1:] * 40) + "\n")
    summary = run_pipeline(data_dir, db_url)
    assert summary.status == "FAILED_VALIDATION"
    c = counts(db_url)
    assert (c["matches"], c["deliveries"]) == (0, 0)
    assert c["etl_run_log"] == 1 and c["dq_issue"] >= 1


def test_dry_run_loads_nothing(data_dir, db_url):
    summary = run_pipeline(data_dir, db_url, dry_run=True)
    assert summary.status == "DRY_RUN"
    assert counts(db_url)["deliveries"] == 0
