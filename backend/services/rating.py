from backend.database import scalar
from backend.services.match_teams import team_ids, team_rating_average, winner_team


def expected_score(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def apply_rating_for_match(conn, match_id):
    existing = scalar(conn, "SELECT COUNT(*) FROM rating_history WHERE match_id = ?", (match_id,))
    if existing:
        return

    row = conn.execute(
        """
        SELECT
            m.id, m.season_id, m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.id = ? AND m.status = 'confirmed'
        """,
        (match_id,),
    ).fetchone()
    if not row:
        return

    team_a = team_ids(row, "A")
    team_b = team_ids(row, "B")
    winning_side = winner_team(row)
    if winning_side not in ("A", "B") or not team_a or not team_b:
        return

    rating_a = team_rating_average(conn, team_a)
    rating_b = team_rating_average(conn, team_b)
    expected_a = expected_score(rating_a, rating_b)
    expected_winner = expected_a if winning_side == "A" else 1 - expected_a
    k_factor = 32
    delta = max(1, round(k_factor * (1 - expected_winner)))
    winners = team_a if winning_side == "A" else team_b
    losers = team_b if winning_side == "A" else team_a

    for user_id in winners:
        before = int(conn.execute("SELECT rating FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()["rating"])
        after = before + delta
        conn.execute("UPDATE player_profiles SET rating = ? WHERE user_id = ?", (after, user_id))
        conn.execute(
            """
            INSERT INTO rating_history (user_id, match_id, season_id, rating_before, rating_after, delta, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, match_id, row["season_id"], before, after, delta, "team_win"),
        )
    for user_id in losers:
        before = int(conn.execute("SELECT rating FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()["rating"])
        after = before - delta
        conn.execute("UPDATE player_profiles SET rating = ? WHERE user_id = ?", (after, user_id))
        conn.execute(
            """
            INSERT INTO rating_history (user_id, match_id, season_id, rating_before, rating_after, delta, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, match_id, row["season_id"], before, after, -delta, "team_loss"),
        )
