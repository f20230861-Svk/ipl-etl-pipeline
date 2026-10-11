"""Pipeline settings: expected columns, cleaning rules and validation thresholds."""

# Franchises that changed names; mapped to the current name so team-level
# queries do not split one franchise into two.
TEAM_RENAMES = {
    "Delhi Daredevils": "Delhi Capitals",
    "Kings XI Punjab": "Punjab Kings",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
}

# Columns the ball-by-ball files must contain. A file missing any of these is
# rejected before anything is loaded.
BALL_REQUIRED = [
    "match_id", "start_date", "innings", "ball", "batting_team", "bowling_team",
    "striker", "runs_off_bat", "extras",
]
# Loaded when present, stored as NULL (or 0 for the extras columns) when absent.
BALL_OPTIONAL = [
    "non_striker", "bowler", "wides", "noballs", "byes", "legbyes", "penalty",
    "wicket_type", "player_dismissed",
]
EXTRAS_COLUMNS = ["wides", "noballs", "byes", "legbyes", "penalty"]

# Keys read from the `info,<key>,<value>` rows of each *_info.csv file.
INFO_KEYS = [
    "date", "venue", "city", "toss_winner", "toss_decision", "winner",
    "winner_runs", "winner_wickets", "method", "player_of_match",
]

TEAM_COLUMNS_MATCHES = ["team1", "team2", "toss_winner", "winner"]
TEAM_COLUMNS_BALLS = ["batting_team", "bowling_team"]

# Validation thresholds
MAX_DELIVERIES_PER_MATCH = 450   # a T20 is ~240; the original double-count gave ~476
MIN_DELIVERIES_PER_MATCH = 60    # below this the match is probably truncated or abandoned
VALID_INNINGS = range(1, 7)      # innings 3-6 cover super overs
MAX_RUNS_OFF_BAT = 7
FIRST_IPL_SEASON = 2008
LAST_PLAUSIBLE_SEASON = 2030
