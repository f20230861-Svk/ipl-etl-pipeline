# IPL Ball-by-Ball ETL Pipeline

A Python pipeline that takes raw [Cricsheet](https://cricsheet.org) IPL CSV files, validates them, cleans them and loads them into PostgreSQL, with a log of every run.

It rebuilds the data layer of my [Impact Player rule analysis](https://github.com/f20230861-Svk/ipl-impact-player-analysis). In that project I loaded the data by hand in a notebook, and a combined `all_matches.csv` file silently double-counted every ball (476 deliveries per match instead of about 240). I only found it by chance. This pipeline turns that cleanup into repeatable code: the defect is now rejected automatically, the cleaning rules live in one place, and every run leaves an audit trail.

## How it works

```
CSV files ──► extract ──► validate (raw) ──► transform ──► validate (clean) ──► load ──► run log
 <id>.csv      find files    structure,        season,        season range,        one          etl_run_log
 <id>_info.csv read frames   duplicates,       renames,       winner sanity        transaction  dq_issue
                             counts            derived cols                        + reconcile
```

| Step | Module | What it does |
|---|---|---|
| Extract | `etl/extract.py` | Sorts files by name: only `<id>.csv` is ball data, `<id>_info.csv` is match metadata, anything else (such as `all_matches.csv`) is skipped and logged. |
| Validate | `etl/validate.py` | Runs data-quality checks (below). Any `ERROR` stops the run before anything is written. |
| Transform | `etl/transform.py` | Season from the match date, merges renamed franchises, numeric coercion, derived columns. |
| Load | `etl/load.py` | Replaces the rows for the loaded matches in a single transaction, then checks the database row counts match what was sent. A mismatch rolls everything back. |
| Orchestrate | `etl/pipeline.py` | Runs the steps in order and writes `etl_run_log` and `dq_issue`. |

### Data-quality checks

| Check | Severity |
|---|---|
| Required ball columns present | ERROR |
| `match_id` inside a file equals its file name | ERROR |
| A match appears in more than one file (the double-count defect) | ERROR |
| More than 450 deliveries in a match (a T20 has about 240) | ERROR |
| Deliveries with no match info | ERROR |
| Nulls in key columns, non-numeric values, innings outside 1–6 | ERROR |
| Season outside 2008–2030 | ERROR |
| Non-match files skipped, abandoned matches, rain-shortened matches | WARNING |
| Winner is neither team, `runs_off_bat` outside 0–7 | WARNING |
| Rain-affected (DLS) matches present, matches with no winner | INFO |

### Design decisions

- **Idempotent loads.** Re-running on the same files gives the same database. New seasons can be added without touching existing matches.
- **`over_number` is stored, not computed in queries.** `CAST(ball AS INT)` truncates in SQLite but rounds in PostgreSQL, so the same notebook SQL would silently change results. The pipeline stores `FLOOR(ball)` once.
- **The audit trail survives failures.** Run logging has its own transaction, so a failed load still leaves a `FAILED_*` row and its data-quality issues.
- **One schema definition for both databases** (`etl/schema.py`, SQLAlchemy), so tests run on SQLite and PostgreSQL.

## Results on the full IPL dataset

Run against the complete Cricsheet IPL download (PostgreSQL 16):

| Check | Result |
|---|---|
| Matches / deliveries loaded | 1,243 / 295,732, matching the published analysis exactly |
| Average deliveries per match | 237.9 (the double-counted file gave about 476) |
| `all_matches.csv` in the folder | Skipped automatically and logged as a warning |
| `all_matches.csv` renamed to look like a match file | Run rejected with 3 errors (largest match: 538 deliveries); nothing loaded |
| Re-running on the same files | Same row counts, both runs recorded in `etl_run_log` |
| First-innings mean, 2019–22 vs 2023–26 (DLS excluded) | 166.9 vs 188.5, +21.6 runs, Welch p = 6.2e-13 |
| Placebo, 2015–18 vs 2019–22 | 167.4 vs 166.9, p = 0.865 |
| Close finishes, before vs after | 35% vs 29% |

`scripts/verify_findings.py` reproduces these numbers from the database.

## Run it

```bash
pip install -r requirements.txt

# Download ipl_csv2.zip from https://cricsheet.org/downloads/ and unzip into data/ipl_csv2/
export DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ipl

python -m etl.pipeline --data-dir data/ipl_csv2            # full run
python -m etl.pipeline --data-dir data/ipl_csv2 --dry-run  # validate only, load nothing
python scripts/verify_findings.py                          # re-derive the analysis numbers from the database
```

Without `DATABASE_URL` it writes to a local `ipl.db` (SQLite). To refresh on a schedule, put the same command in cron, for example `0 6 * * 1 cd /path/to/repo && python -m etl.pipeline --data-dir data/ipl_csv2`.

Check past runs:

```sql
SELECT run_id, status, matches_loaded, deliveries_loaded, errors, warnings FROM etl_run_log ORDER BY run_id DESC;
SELECT check_name, severity, detail, affected_count FROM dq_issue WHERE run_id = 1;
```

## Tests

```bash
pytest                                                                    # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost/test pytest      # SQLite and PostgreSQL
```

The tests build a small Cricsheet-style dataset (including a bad combined file) and cover file discovery, parsing, cleaning rules, each validation check, an end-to-end load with its audit trail, idempotent re-runs, rejection of bad data with nothing loaded, and dry runs.

## Schema

`matches` (one row per match), `deliveries` (one row per ball, foreign key to `matches`), `etl_run_log` (one row per run), `dq_issue` (one row per issue per run).
