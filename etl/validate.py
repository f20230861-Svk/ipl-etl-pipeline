"""Validate: data-quality checks run before anything is loaded.

Severities
  ERROR    - the run stops and nothing is written to the database.
  WARNING  - logged, the run continues.
  INFO     - logged for the record.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"


@dataclass(frozen=True)
class Issue:
    check: str
    severity: str
    detail: str
    count: int = 0


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == ERROR for i in issues)


def validate_raw(balls: pd.DataFrame, info: pd.DataFrame, skipped: list[Path]) -> list[Issue]:
    """Structural checks on the data exactly as read from the files."""
    issues: list[Issue] = []

    if skipped:
        names = ", ".join(sorted(p.name for p in skipped)[:5])
        issues.append(Issue("non_match_files_skipped", WARNING,
                            f"Skipped files that are not per-match CSVs: {names}", len(skipped)))

    missing = [c for c in config.BALL_REQUIRED if c not in balls.columns]
    if missing:
        issues.append(Issue("ball_columns_missing", ERROR,
                            f"Ball files lack required columns: {missing}", len(missing)))
    for col in ("match_id", "date", "team1", "team2"):
        if col not in info.columns:
            issues.append(Issue("info_fields_missing", ERROR, f"Info files lack '{col}'", 1))
    if has_errors(issues):
        return issues  # remaining checks assume these columns exist

    # match_id inside each file must equal the file name
    expected_id = balls["source_file"].str.replace(".csv", "", regex=False)
    mismatch = balls[expected_id != balls["match_id"].astype(str)]
    if len(mismatch):
        issues.append(Issue("match_id_matches_filename", ERROR,
                            "match_id inside a file differs from its file name", int(mismatch["source_file"].nunique())))

    # the same match must not arrive from more than one file (the double-count defect)
    files_per_match = balls.groupby("match_id")["source_file"].nunique()
    dupes = files_per_match[files_per_match > 1]
    if len(dupes):
        issues.append(Issue("match_in_multiple_files", ERROR,
                            "Some matches appear in more than one file, which double-counts deliveries", len(dupes)))

    # every delivery needs match metadata, and vice versa
    ball_ids, info_ids = set(balls["match_id"]), set(info["match_id"])
    orphans = ball_ids - info_ids
    if orphans:
        issues.append(Issue("deliveries_without_match_info", ERROR,
                            f"Deliveries for matches with no info file, e.g. {sorted(orphans)[:3]}", len(orphans)))
    no_balls = info_ids - ball_ids
    if no_balls:
        issues.append(Issue("matches_without_deliveries", WARNING,
                            f"Matches with an info file but no ball data (abandoned?), e.g. {sorted(no_balls)[:3]}", len(no_balls)))

    # required values present
    for col in ("match_id", "innings", "ball", "batting_team", "bowling_team", "runs_off_bat", "extras"):
        nulls = int(balls[col].isna().sum())
        if nulls:
            issues.append(Issue(f"null_{col}", ERROR, f"{nulls} deliveries have no {col}", nulls))

    # numeric columns really numeric
    for col in ("innings", "ball", "runs_off_bat", "extras"):
        bad = int(pd.to_numeric(balls[col], errors="coerce").isna().sum() - balls[col].isna().sum())
        if bad:
            issues.append(Issue(f"non_numeric_{col}", ERROR, f"{bad} non-numeric values in {col}", bad))

    innings = pd.to_numeric(balls["innings"], errors="coerce")
    bad_innings = int((~innings.isin(list(config.VALID_INNINGS))).sum() - innings.isna().sum())
    if bad_innings:
        issues.append(Issue("innings_out_of_range", ERROR,
                            f"innings outside {config.VALID_INNINGS.start}-{config.VALID_INNINGS.stop - 1}", bad_innings))

    runs = pd.to_numeric(balls["runs_off_bat"], errors="coerce")
    odd_runs = int(((runs < 0) | (runs > config.MAX_RUNS_OFF_BAT)).sum())
    if odd_runs:
        issues.append(Issue("runs_off_bat_out_of_range", WARNING,
                            f"runs_off_bat outside 0-{config.MAX_RUNS_OFF_BAT}", odd_runs))

    # deliveries per match: catches double-counting even if the file-name rule is bypassed
    per_match = balls.groupby("match_id").size()
    too_many = per_match[per_match > config.MAX_DELIVERIES_PER_MATCH]
    if len(too_many):
        issues.append(Issue("too_many_deliveries_per_match", ERROR,
                            f"{len(too_many)} matches exceed {config.MAX_DELIVERIES_PER_MATCH} deliveries "
                            f"(max {int(too_many.max())}); likely double-counting", len(too_many)))
    too_few = per_match[per_match < config.MIN_DELIVERIES_PER_MATCH]
    if len(too_few):
        issues.append(Issue("few_deliveries_per_match", WARNING,
                            f"{len(too_few)} matches have under {config.MIN_DELIVERIES_PER_MATCH} deliveries "
                            "(rain-shortened or incomplete)", len(too_few)))

    if info["match_id"].duplicated().any():
        issues.append(Issue("duplicate_info_files", ERROR, "Same match_id in more than one info file",
                            int(info["match_id"].duplicated().sum())))
    return issues


def validate_clean(matches: pd.DataFrame, deliveries: pd.DataFrame) -> list[Issue]:
    """Semantic checks on the cleaned tables."""
    issues: list[Issue] = []

    bad_season = matches[~matches["season"].between(config.FIRST_IPL_SEASON, config.LAST_PLAUSIBLE_SEASON)]
    if len(bad_season):
        issues.append(Issue("season_out_of_range", ERROR,
                            f"Seasons outside {config.FIRST_IPL_SEASON}-{config.LAST_PLAUSIBLE_SEASON}", len(bad_season)))

    has_winner = matches["winner"].notna()
    not_playing = matches[has_winner & (matches["winner"] != matches["team1"]) & (matches["winner"] != matches["team2"])]
    if len(not_playing):
        issues.append(Issue("winner_not_a_participant", WARNING,
                            "Winner is neither team1 nor team2", len(not_playing)))

    dls = int(matches["method"].notna().sum())
    if dls:
        issues.append(Issue("dls_matches_flagged", INFO,
                            "Rain-affected (DLS) matches kept in the data; filter on method IS NULL for score comparisons", dls))

    no_result = int((~has_winner).sum())
    if no_result:
        issues.append(Issue("matches_without_winner", INFO, "Matches with no recorded winner", no_result))

    unmatched = set(deliveries["match_id"]) - set(matches["match_id"])
    if unmatched:
        issues.append(Issue("deliveries_without_match", ERROR, "Deliveries reference unknown matches", len(unmatched)))
    return issues
