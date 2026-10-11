"""Builds a tiny Cricsheet-style dataset on disk for tests."""
from __future__ import annotations

import csv
from pathlib import Path

BALL_COLUMNS = ["match_id", "season", "start_date", "venue", "innings", "ball", "batting_team",
                "bowling_team", "striker", "non_striker", "bowler", "runs_off_bat", "extras",
                "wides", "noballs", "byes", "legbyes", "penalty", "wicket_type", "player_dismissed"]

# match_id, date, season label in the source, team1, team2, winner, winner_runs, method
MATCHES = [
    (1001, "2008-04-19", "2007/08", "Delhi Daredevils", "Kings XI Punjab", "Delhi Daredevils", "10", ""),
    (1002, "2023-04-01", "2023", "Chennai Super Kings", "Gujarat Titans", "Chennai Super Kings", "5", ""),
    (1003, "2023-04-02", "2023", "Mumbai Indians", "Rajasthan Royals", "Mumbai Indians", "8", "D/L"),
]


def _ball_rows(match_id: int, date: str, team1: str, team2: str) -> list[dict]:
    rows = []
    for innings, (bat, bowl) in enumerate([(team1, team2), (team2, team1)], start=1):
        for i in range(1, 8):  # 6 legal balls + 1 wide on ball 0.6
            is_wide = i == 7
            ball = 0.6 if is_wide else round(0.1 * i, 1)
            rows.append({
                "match_id": match_id, "season": date[:4], "start_date": date, "venue": "Test Ground",
                "innings": innings, "ball": ball, "batting_team": bat, "bowling_team": bowl,
                "striker": "A Batter", "non_striker": "B Batter", "bowler": "C Bowler",
                "runs_off_bat": 6 if i == 3 else 1, "extras": 1 if is_wide else 0,
                "wides": 1 if is_wide else "", "noballs": "", "byes": "", "legbyes": "",
                "penalty": "", "wicket_type": "", "player_dismissed": "",
            })
    return rows


def write_dataset(folder: Path, with_combined_file: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    for match_id, date, season_label, t1, t2, winner, win_runs, method in MATCHES:
        rows = _ball_rows(match_id, date, t1, t2)
        all_rows += rows
        with open(folder / f"{match_id}.csv", "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=BALL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        info = [
            ["version", "2.0.0"],
            ["info", "team", t1], ["info", "team", t2],
            ["info", "gender", "male"],
            ["info", "season", season_label],
            ["info", "date", date],
            ["info", "venue", "Test Ground"], ["info", "city", "Testville"],
            ["info", "toss_winner", t1], ["info", "toss_decision", "bat"],
            ["info", "winner", winner], ["info", "winner_runs", win_runs],
            ["info", "player_of_match", "A Batter"],
            ["info", "player", t1, "A Batter"],  # 4-field rows must be ignored
        ]
        if method:
            info.append(["info", "method", method])
        with open(folder / f"{match_id}_info.csv", "w", newline="") as fh:
            csv.writer(fh).writerows(info)

    if with_combined_file:  # the defect that originally double-counted every ball
        with open(folder / "all_matches.csv", "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=BALL_COLUMNS)
            writer.writeheader()
            writer.writerows(all_rows)
    return folder


TOTAL_DELIVERIES = len(MATCHES) * 14
