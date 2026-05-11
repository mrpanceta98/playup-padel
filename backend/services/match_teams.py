def row_value(row, key, default=None):
    if row is None:
        return default
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def team_ids(match, side):
    if side == "A":
        ids = [row_value(match, "team_a_player_1_id"), row_value(match, "team_a_player_2_id")]
        legacy = row_value(match, "player_a_id")
    else:
        ids = [row_value(match, "team_b_player_1_id"), row_value(match, "team_b_player_2_id")]
        legacy = row_value(match, "player_b_id")
    ids = [int(user_id) for user_id in ids if user_id]
    return ids or ([int(legacy)] if legacy else [])


def participant_ids(match):
    return team_ids(match, "A") + team_ids(match, "B")


def player_team(match, user_id):
    if user_id in team_ids(match, "A"):
        return "A"
    if user_id in team_ids(match, "B"):
        return "B"
    return None


def other_team(side):
    return "B" if side == "A" else "A"


def winner_team(match):
    explicit = row_value(match, "winner_team")
    if explicit in ("A", "B"):
        return explicit
    winner_id = row_value(match, "winner_id")
    return player_team(match, winner_id) if winner_id else None


def loser_team(match):
    explicit = row_value(match, "loser_team")
    if explicit in ("A", "B"):
        return explicit
    winner = winner_team(match)
    return other_team(winner) if winner else None


def team_rating_average(conn, users):
    if not users:
        return 0
    placeholders = ",".join("?" for _ in users)
    rows = conn.execute(f"SELECT rating FROM player_profiles WHERE user_id IN ({placeholders})", tuple(users)).fetchall()
    return sum(row["rating"] for row in rows) / len(rows) if rows else 0


def team_score_stats(match, side):
    winner = winner_team(match)
    if not winner:
        return {"sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0}
    if side == winner:
        return {
            "sets_won": row_value(match, "sets_won_winner", 0),
            "sets_lost": row_value(match, "sets_won_loser", 0),
            "games_won": row_value(match, "games_won_winner", 0),
            "games_lost": row_value(match, "games_won_loser", 0),
        }
    return {
        "sets_won": row_value(match, "sets_won_loser", 0),
        "sets_lost": row_value(match, "sets_won_winner", 0),
        "games_won": row_value(match, "games_won_loser", 0),
        "games_lost": row_value(match, "games_won_winner", 0),
    }


def first_or_none(values):
    return values[0] if values else None
