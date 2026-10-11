"""Transform: clean the raw frames into the shapes stored in the database."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def _rename_teams(frame: pd.DataFrame, columns: list[str]) -> None:
    for col in columns:
        if col in frame.columns:
            frame[col] = frame[col].replace(config.TEAM_RENAMES)


def clean_matches(info: pd.DataFrame) -> pd.DataFrame:
    """One row per match, with season taken from the match date.

    Cricsheet labels some seasons '2007/08'; the year the match was actually
    played is used instead, so every season is a single integer.
    """
    out = pd.DataFrame({"match_id": info["match_id"].astype(int)})
    dates = pd.to_datetime(info["date"], errors="coerce")
    out["season"] = dates.dt.year
    out["date"] = dates.dt.date

    for col in config.INFO_KEYS:
        if col == "date":
            continue
        out[col] = info[col] if col in info.columns else None
    out["team1"], out["team2"] = info["team1"], info["team2"]
    out["source_file"] = info["source_file"]

    for col in ("winner_runs", "winner_wickets"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    _rename_teams(out, config.TEAM_COLUMNS_MATCHES)
    columns = ["match_id", "season", "date", "venue", "city", "team1", "team2", "toss_winner",
               "toss_decision", "winner", "winner_runs", "winner_wickets", "method",
               "player_of_match", "source_file"]
    return out[columns].sort_values("match_id").reset_index(drop=True)


def clean_deliveries(balls: pd.DataFrame) -> pd.DataFrame:
    """One row per delivery, with derived columns the SQL layer can rely on.

    - season: year of start_date (same rule as matches)
    - over_number: the 0-based over, FLOOR(ball). Stored so queries do not depend on
      how each database rounds CAST(ball AS INT) (SQLite truncates, PostgreSQL rounds).
    - is_legal_delivery: not a wide or a no-ball
    """
    out = pd.DataFrame(index=balls.index)
    out["match_id"] = balls["match_id"].astype(int)
    out["season"] = pd.to_datetime(balls["start_date"], errors="coerce").dt.year
    out["innings"] = pd.to_numeric(balls["innings"]).astype(int)

    ball = pd.to_numeric(balls["ball"]).round(1)
    out["ball"] = ball
    out["over_number"] = np.floor(ball).astype(int)

    for col in ("batting_team", "bowling_team", "striker"):
        out[col] = balls[col]
    for col in ("non_striker", "bowler", "wicket_type", "player_dismissed"):
        out[col] = balls[col] if col in balls.columns else None

    out["runs_off_bat"] = pd.to_numeric(balls["runs_off_bat"]).astype(int)
    out["extras"] = pd.to_numeric(balls["extras"]).astype(int)
    for col in config.EXTRAS_COLUMNS:
        series = pd.to_numeric(balls[col], errors="coerce") if col in balls.columns else 0
        out[col] = pd.Series(series, index=balls.index).fillna(0).astype(int)

    out["is_legal_delivery"] = (out["wides"] == 0) & (out["noballs"] == 0)
    out["source_file"] = balls["source_file"]

    _rename_teams(out, config.TEAM_COLUMNS_BALLS)
    columns = ["match_id", "season", "innings", "ball", "over_number", "batting_team", "bowling_team",
               "striker", "non_striker", "bowler", "runs_off_bat", "extras", "wides", "noballs",
               "byes", "legbyes", "penalty", "wicket_type", "player_dismissed",
               "is_legal_delivery", "source_file"]
    return out[columns].sort_values(["match_id", "innings", "ball"], kind="stable").reset_index(drop=True)
