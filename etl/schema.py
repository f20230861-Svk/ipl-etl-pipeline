"""Database schema, defined once with SQLAlchemy so it works on PostgreSQL and SQLite."""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, MetaData, Numeric, Table, Text,
    func,
)

metadata = MetaData()

matches = Table(
    "matches", metadata,
    Column("match_id", Integer, primary_key=True, autoincrement=False),
    Column("season", Integer, nullable=False),
    Column("date", Date, nullable=False),
    Column("venue", Text),
    Column("city", Text),
    Column("team1", Text, nullable=False),
    Column("team2", Text, nullable=False),
    Column("toss_winner", Text),
    Column("toss_decision", Text),
    Column("winner", Text),
    Column("winner_runs", Integer),
    Column("winner_wickets", Integer),
    Column("method", Text),  # 'D/L' for rain-affected matches, NULL otherwise
    Column("player_of_match", Text),
    Column("source_file", Text, nullable=False),
)

deliveries = Table(
    "deliveries", metadata,
    Column("delivery_id", Integer, primary_key=True, autoincrement=True),
    Column("match_id", Integer, ForeignKey("matches.match_id"), nullable=False),
    Column("season", Integer, nullable=False),  # denormalised from matches for simpler queries
    Column("innings", Integer, nullable=False),
    Column("ball", Numeric(5, 1), nullable=False),
    Column("over_number", Integer, nullable=False),
    Column("batting_team", Text, nullable=False),
    Column("bowling_team", Text, nullable=False),
    Column("striker", Text),
    Column("non_striker", Text),
    Column("bowler", Text),
    Column("runs_off_bat", Integer, nullable=False),
    Column("extras", Integer, nullable=False),
    Column("wides", Integer, nullable=False, server_default="0"),
    Column("noballs", Integer, nullable=False, server_default="0"),
    Column("byes", Integer, nullable=False, server_default="0"),
    Column("legbyes", Integer, nullable=False, server_default="0"),
    Column("penalty", Integer, nullable=False, server_default="0"),
    Column("wicket_type", Text),
    Column("player_dismissed", Text),
    Column("is_legal_delivery", Boolean, nullable=False),
    Column("source_file", Text, nullable=False),
)
Index("ix_deliveries_match", deliveries.c.match_id)
Index("ix_deliveries_season_innings", deliveries.c.season, deliveries.c.innings)

etl_run_log = Table(
    "etl_run_log", metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", DateTime, nullable=False, server_default=func.now()),
    Column("finished_at", DateTime),
    Column("status", Text, nullable=False),  # RUNNING | SUCCESS | DRY_RUN | FAILED_VALIDATION | FAILED_ERROR
    Column("match_files", Integer),
    Column("skipped_files", Integer),
    Column("matches_extracted", Integer),
    Column("deliveries_extracted", Integer),
    Column("matches_loaded", Integer),
    Column("deliveries_loaded", Integer),
    Column("errors", Integer),
    Column("warnings", Integer),
    Column("message", Text),
)

dq_issue = Table(
    "dq_issue", metadata,
    Column("issue_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("etl_run_log.run_id"), nullable=False),
    Column("check_name", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("detail", Text),
    Column("affected_count", Integer),
)
