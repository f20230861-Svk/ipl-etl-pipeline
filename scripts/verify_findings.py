"""Re-derive the headline findings of the IPL analysis from the pipeline's database.

The earlier notebook loaded the data by hand. If the pipeline is correct, the
same SQL on the pipeline's tables must give the same numbers.

    python scripts/verify_findings.py --db-url postgresql+psycopg://user:pw@localhost/ipl
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text

# Published in the analysis README (https://github.com/f20230861-Svk/ipl-impact-player-analysis)
EXPECTED = {
    "matches": 1243,
    "deliveries": 295_732,
    "first_innings_2019_22": 166.9,
    "first_innings_2023_26": 188.5,
    "placebo_2015_18": 167.4,
    "placebo_2019_22": 166.9,
    "placebo_p": 0.87,  # published rounded from 0.865
}

FIRST_INNINGS_SQL = """
SELECT d.match_id, d.season, SUM(d.runs_off_bat + d.extras) AS total
FROM deliveries d JOIN matches m ON d.match_id = m.match_id
WHERE d.innings = 1 AND m.method IS NULL
GROUP BY d.match_id, d.season
"""

SIXES_SQL = """
SELECT season,
       1.0 * SUM(CASE WHEN runs_off_bat = 6 THEN 1 ELSE 0 END) / COUNT(DISTINCT match_id) AS sixes_per_match
FROM deliveries WHERE innings <= 2 GROUP BY season ORDER BY season
"""

CLOSE_FINISH_SQL = """
WITH last_over AS (
  SELECT match_id, MAX(over_number) AS lo FROM deliveries WHERE innings = 2 GROUP BY match_id
)
SELECT m.season,
       CASE WHEN m.winner_runs <= 10 OR (m.winner_wickets IS NOT NULL AND l.lo >= 19) THEN 1 ELSE 0 END AS close
FROM matches m JOIN last_over l ON m.match_id = l.match_id
WHERE m.winner IS NOT NULL AND m.method IS NULL
"""


def check(label: str, got: float, want: float, tol: float) -> bool:
    ok = abs(got - want) <= tol
    print(f"  [{'PASS' if ok else 'DIFF'}] {label}: pipeline {got:g} vs published {want:g}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL", "sqlite:///ipl.db"))
    engine = create_engine(parser.parse_args().db_url)
    results: list[bool] = []

    with engine.connect() as conn:
        n_matches = conn.execute(text("SELECT COUNT(*) FROM matches")).scalar_one()
        n_balls = conn.execute(text("SELECT COUNT(*) FROM deliveries")).scalar_one()
        print("Row counts")
        results.append(check("matches", n_matches, EXPECTED["matches"], 0))
        results.append(check("deliveries", n_balls, EXPECTED["deliveries"], 0))

        fi = pd.read_sql(text(FIRST_INNINGS_SQL), conn)
        sixes = pd.read_sql(text(SIXES_SQL), conn)
        close = pd.read_sql(text(CLOSE_FINISH_SQL), conn)

    def block(lo: int, hi: int) -> pd.Series:
        return fi[fi.season.between(lo, hi)]["total"].astype(float)

    before, after = block(2019, 2022), block(2023, 2026)
    early = block(2015, 2018)
    if len(before) and len(after) and len(early):
        print("First-innings scores (DLS matches excluded)")
        results.append(check("mean 2019-22", round(before.mean(), 1), EXPECTED["first_innings_2019_22"], 0.05))
        results.append(check("mean 2023-26", round(after.mean(), 1), EXPECTED["first_innings_2023_26"], 0.05))
        t, p = stats.ttest_ind(after, before, equal_var=False)
        print(f"  Welch t-test after vs before: diff {after.mean() - before.mean():.1f} runs, p = {p:.2e}")
        results.append(check("placebo mean 2015-18", round(early.mean(), 1), EXPECTED["placebo_2015_18"], 0.05))
        pp = stats.ttest_ind(before, early, equal_var=False).pvalue
        results.append(check("placebo p-value, 2015-18 -> 2019-22", round(pp, 3), EXPECTED["placebo_p"], 0.01))
    else:
        print("Not enough seasons loaded for the before/after comparison")

    eras = sixes.assign(era=sixes.season.map(lambda s: "2023-26" if s >= 2023 else ("2019-22" if s >= 2019 else None)))
    eras = eras.dropna(subset=["era"]).groupby("era")["sixes_per_match"].mean()
    if len(eras) == 2:
        print(f"Sixes per match (mean of seasons): 2019-22 {eras['2019-22']:.1f}, 2023-26 {eras['2023-26']:.1f}")

    close["era"] = close.season.map(lambda s: "after" if s >= 2023 else ("before" if s >= 2019 else None))
    close = close.dropna(subset=["era"])
    if close.era.nunique() == 2:
        rate = close.groupby("era")["close"].mean() * 100
        print(f"Close finishes: before {rate['before']:.0f}%, after {rate['after']:.0f}% (published 35% -> 29%)")

    print("\nAll deterministic checks passed" if all(results) else "\nSome checks differ; investigate before trusting the pipeline")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
