"""Extract: find the Cricsheet CSV files and read them into DataFrames."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class SourceFiles:
    match_files: list[Path] = field(default_factory=list)  # <id>.csv, ball by ball
    info_files: list[Path] = field(default_factory=list)   # <id>_info.csv, match metadata
    skipped: list[Path] = field(default_factory=list)      # everything else


def discover(data_dir: str | Path) -> SourceFiles:
    """Sort the CSVs in a folder into match files, info files and skipped files.

    Only files named `<digits>.csv` count as match files. A combined file such as
    `all_matches.csv` is skipped by this rule; loading it next to the per-match
    files double-counts every delivery.
    """
    folder = Path(data_dir)
    if not folder.is_dir():
        raise FileNotFoundError(f"Data directory not found: {folder}")

    found = SourceFiles()
    for path in sorted(folder.glob("*.csv")):
        stem = path.stem
        if stem.isdigit():
            found.match_files.append(path)
        elif stem.endswith("_info") and stem[: -len("_info")].isdigit():
            found.info_files.append(path)
        else:
            found.skipped.append(path)
    return found


def read_balls(files: list[Path]) -> pd.DataFrame:
    """Read all ball-by-ball files into one frame, tagging each row with its file."""
    frames = []
    for path in files:
        frame = pd.read_csv(path, low_memory=False)
        frame["source_file"] = path.name
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def read_info(files: list[Path]) -> pd.DataFrame:
    """Parse the `info,<key>,<value>` rows of each info file into one row per match."""
    rows = []
    for path in files:
        match: dict = {"match_id": int(path.stem.split("_")[0]), "source_file": path.name}
        teams: list[str] = []
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) == 3 and row[0] == "info":
                    key, value = row[1], row[2]
                    if key == "team":
                        teams.append(value)
                    elif key not in match:
                        match[key] = value
        if len(teams) >= 2:
            match["team1"], match["team2"] = teams[0], teams[1]
        rows.append(match)
    return pd.DataFrame(rows)
