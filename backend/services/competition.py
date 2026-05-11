import calendar
import functools
import json
from datetime import date

from backend.database import rows_to_dicts, scalar
from backend.services.gamification import apply_monthly_achievements
from backend.services.grouping import create_groups_for_season
from backend.services.match_teams import loser_team, player_team, team_ids, team_score_stats, winner_team


def parse_score(score):
    parts = score.strip().split()
    if not parts:
        raise ValueError("Usa formato 6-4 4-6 10-8.")
    sets = []
    for part in parts:
        raw = part.split("-")
        if len(raw) != 2:
            raise ValueError("Usa formato 6-4 4-6 10-8.")
        try:
            a_games = int(raw[0])
            b_games = int(raw[1])
        except ValueError as exc:
            raise ValueError("El marcador solo puede contener numeros.") from exc
        if a_games == b_games or min(a_games, b_games) < 0:
            raise ValueError("Cada set debe tener ganador.")
        sets.append((a_games, b_games))

    a_sets = sum(1 for a, b in sets if a > b)
    b_sets = sum(1 for a, b in sets if b > a)
    if a_sets == b_sets:
        raise ValueError("El partido debe tener ganador por sets.")

    return {
        "winner_side": "A" if a_sets > b_sets else "B",
        "a": {
            "sets_won": a_sets,
            "sets_lost": b_sets,
            "games_won": sum(a for a, _ in sets),
            "games_lost": sum(b for _, b in sets),
        },
        "b": {
            "sets_won": b_sets,
            "sets_lost": a_sets,
            "games_won": sum(b for _, b in sets),
            "games_lost": sum(a for a, _ in sets),
        },
    }


def confirmed_match_rows(conn, season_id, group_id):
    return conn.execute(
        """
        SELECT
            m.id, m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            m.created_at, m.is_walkover,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team, r.score,
            r.sets_won_winner, r.sets_won_loser, r.games_won_winner, r.games_won_loser,
            pa.rating AS rating_a_1, pa2.rating AS rating_a_2, pb.rating AS rating_b_1, pb2.rating AS rating_b_2
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        JOIN player_profiles pa ON pa.user_id = m.player_a_id
        JOIN player_profiles pb ON pb.user_id = m.player_b_id
        LEFT JOIN player_profiles pa2 ON pa2.user_id = m.team_a_player_2_id
        LEFT JOIN player_profiles pb2 ON pb2.user_id = m.team_b_player_2_id
        WHERE m.season_id = ? AND m.group_id = ? AND m.status = 'confirmed' AND m.counts_for_ranking = 1
        ORDER BY m.created_at ASC, m.id ASC
        """,
        (season_id, group_id),
    ).fetchall()


def result_for_player(match, user_id):
    side = player_team(match, user_id)
    if not side:
        return None
    won = winner_team(match) == side
    lost = loser_team(match) == side
    opponent_ids = team_ids(match, "B" if side == "A" else "A")
    opponent_ratings = []
    for opponent_id in opponent_ids:
        if opponent_id == match["team_a_player_1_id"] or opponent_id == match["player_a_id"]:
            opponent_ratings.append(match["rating_a_1"])
        elif opponent_id == match["team_a_player_2_id"]:
            opponent_ratings.append(match["rating_a_2"] or match["rating_a_1"])
        elif opponent_id == match["team_b_player_1_id"] or opponent_id == match["player_b_id"]:
            opponent_ratings.append(match["rating_b_1"])
        elif opponent_id == match["team_b_player_2_id"]:
            opponent_ratings.append(match["rating_b_2"] or match["rating_b_1"])
    opponent_rating = sum(opponent_ratings) / len(opponent_ratings) if opponent_ratings else 0
    stats = team_score_stats(match, side)
    points = 3 if won else 1
    if lost and match["is_walkover"]:
        points = 0

    return {
        "match_id": match["id"],
        "opponent_id": opponent_ids[0] if opponent_ids else None,
        "opponent_rating": opponent_rating,
        "points": points,
        "win": 1 if won else 0,
        "loss": 1 if lost else 0,
        "walkover": 1 if lost and match["is_walkover"] else 0,
        "set_average": stats["sets_won"] - stats["sets_lost"],
        "game_average": stats["games_won"] - stats["games_lost"],
        "created_at": match["created_at"],
    }


def best_10_results(results):
    return sorted(
        results,
        key=lambda item: (
            -item["points"],
            -item["set_average"],
            -item["game_average"],
            -item["opponent_rating"],
            item["created_at"],
        ),
    )[:10]


def head_to_head(conn, season_id, group_id, left_id, right_id):
    rows = conn.execute(
        """
        SELECT
            m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.season_id = ?
          AND m.group_id = ?
          AND m.status = 'confirmed'
        ORDER BY m.created_at DESC, m.id DESC
        """,
        (season_id, group_id),
    ).fetchall()
    for row in rows:
        left_team = player_team(row, left_id)
        right_team = player_team(row, right_id)
        if not left_team or not right_team or left_team == right_team:
            continue
        winner = winner_team(row)
        if winner == left_team:
            return -1
        if winner == right_team:
            return 1
    return 0


def compare_ranking_rows(conn, season_id, group_id, left, right):
    checks = [
        right["points"] - left["points"],
        right["set_average"] - left["set_average"],
        right["game_average"] - left["game_average"],
        (right["opponent_strength"] > left["opponent_strength"]) - (right["opponent_strength"] < left["opponent_strength"]),
    ]
    for value in checks:
        if value:
            return value
    h2h = head_to_head(conn, season_id, group_id, left["user_id"], right["user_id"])
    if h2h:
        return h2h
    if left["played"] != right["played"]:
        return left["played"] - right["played"]
    return (left["display_name"] > right["display_name"]) - (left["display_name"] < right["display_name"])


def sort_ranking_rows(conn, season_id, group_id, rows):
    return sorted(rows, key=functools.cmp_to_key(lambda left, right: compare_ranking_rows(conn, season_id, group_id, left, right)))


def ranking_for_group(conn, season_id, group_id, persist=False):
    members = conn.execute(
        """
        SELECT u.id AS user_id, u.email, p.display_name, p.rating, d.name AS division_name,
               ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
        FROM group_members gm
        JOIN users u ON u.id = gm.user_id
        JOIN player_profiles p ON p.user_id = u.id
        JOIN groups g ON g.id = gm.group_id
        JOIN divisions d ON d.id = g.division_id
        LEFT JOIN user_avatars ua ON ua.user_id = u.id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        WHERE gm.season_id = ? AND gm.group_id = ? AND gm.active = 1
        """,
        (season_id, group_id),
    ).fetchall()
    matches = confirmed_match_rows(conn, season_id, group_id)
    rows = []
    for member in members:
        results = [result_for_player(match, member["user_id"]) for match in matches if member["user_id"] in team_ids(match, "A") + team_ids(match, "B")]
        results = [item for item in results if item]
        valid = best_10_results(results)
        discarded = [item for item in results if item["match_id"] not in {v["match_id"] for v in valid}]
        played = len(valid)
        row = {
            "user_id": member["user_id"],
            "email": member["email"],
            "display_name": member["display_name"],
            "rating": member["rating"],
            "division_name": member["division_name"],
            "avatar_base_image": member["avatar_base_image"],
            "equipped_frame_name": member["equipped_frame_name"],
            "points": sum(item["points"] for item in valid),
            "played": played,
            "wins": sum(item["win"] for item in valid),
            "losses": sum(item["loss"] for item in valid),
            "walkovers": sum(item["walkover"] for item in valid),
            "set_average": sum(item["set_average"] for item in valid),
            "game_average": sum(item["game_average"] for item in valid),
            "opponent_strength": round(sum(item["opponent_rating"] for item in valid) / played, 2) if played else 0,
            "valid_match_ids": [item["match_id"] for item in valid],
            "discarded_match_ids": [item["match_id"] for item in discarded],
        }
        rows.append(row)

    rows = sort_ranking_rows(conn, season_id, group_id, rows)
    promotion_cut = rows[2] if len(rows) >= 3 else None
    relegation_cut = rows[-3] if len(rows) > 6 else None
    for index, row in enumerate(rows, start=1):
        row["rank_position"] = index
        if index == 1:
            row["points_to_next_position"] = 0
        else:
            row["points_to_next_position"] = max(1, rows[index - 2]["points"] + 1 - row["points"])
        if index <= 3:
            row["movement_zone"] = "promotion"
        elif len(rows) > 6 and index > len(rows) - 3:
            row["movement_zone"] = "relegation"
        else:
            row["movement_zone"] = "stay"
        row["promotion_gap_points"] = 0 if index <= 3 else max(1, promotion_cut["points"] + 1 - row["points"]) if promotion_cut else None
        row["relegation_gap_points"] = 0 if row["movement_zone"] == "relegation" else max(1, row["points"] - relegation_cut["points"]) if relegation_cut else None
        if row["movement_zone"] == "promotion":
            row["standing_note"] = "Ascenso"
        elif row["movement_zone"] == "relegation":
            row["standing_note"] = "Descenso"
        elif row["promotion_gap_points"] is not None and row["rank_position"] <= max(6, len(rows) // 2):
            points = row["promotion_gap_points"]
            row["standing_note"] = f"A {points} punto{'s' if points != 1 else ''} del ascenso"
        elif row["relegation_gap_points"] is not None:
            points = row["relegation_gap_points"]
            row["standing_note"] = f"A {points} punto{'s' if points != 1 else ''} del descenso"
        else:
            row["standing_note"] = "Zona media"

    if persist:
        conn.execute("DELETE FROM ranking_entries WHERE season_id = ? AND group_id = ?", (season_id, group_id))
        for row in rows:
            conn.execute(
                """
                INSERT INTO ranking_entries
                (season_id, group_id, user_id, points, played, wins, losses, walkovers, set_average,
                 game_average, opponent_strength, rank_position, valid_match_ids_json, discarded_match_ids_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_id,
                    group_id,
                    row["user_id"],
                    row["points"],
                    row["played"],
                    row["wins"],
                    row["losses"],
                    row["walkovers"],
                    row["set_average"],
                    row["game_average"],
                    row["opponent_strength"],
                    row["rank_position"],
                    json.dumps(row["valid_match_ids"]),
                    json.dumps(row["discarded_match_ids"]),
                ),
            )
    return rows


def recalc_all_rankings(conn, season_id):
    all_rows = []
    groups = conn.execute("SELECT id FROM groups WHERE season_id = ?", (season_id,)).fetchall()
    for group in groups:
        all_rows.extend(ranking_for_group(conn, season_id, group["id"], persist=True))
    return all_rows


def next_division_id(conn, division_id, movement):
    current = conn.execute("SELECT sort_order FROM divisions WHERE id = ?", (division_id,)).fetchone()
    if not current:
        return division_id
    operator = ">" if movement == "promotion" else "<"
    direction = "ASC" if movement == "promotion" else "DESC"
    row = conn.execute(
        f"SELECT id FROM divisions WHERE sort_order {operator} ? ORDER BY sort_order {direction} LIMIT 1",
        (current["sort_order"],),
    ).fetchone()
    return row["id"] if row else division_id


def next_month_season(current):
    start = date.fromisoformat(current["starts_on"])
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    starts_on = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    ends_on = date(year, month, last_day)
    name = f"{calendar.month_name[month]} {year}"
    return name, starts_on.isoformat(), ends_on.isoformat()


def close_monthly_season(conn, season_id):
    season = conn.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if not season or season["status"] == "closed":
        return {"closed": False, "reason": "Season already closed or missing."}

    ranking_rows = recalc_all_rankings(conn, season_id)
    promoted = []
    players_by_division = {}

    groups = conn.execute("SELECT id, division_id FROM groups WHERE season_id = ?", (season_id,)).fetchall()
    for group in groups:
        rows = ranking_for_group(conn, season_id, group["id"], persist=True)
        for row in rows:
            movement = row["movement_zone"]
            target_division = group["division_id"]
            if movement in ("promotion", "relegation"):
                target_division = next_division_id(conn, group["division_id"], movement)
            if movement == "promotion":
                promoted.append(row["user_id"])
            conn.execute(
                """
                INSERT INTO promotion_relegation_history
                (season_id, user_id, from_division_id, to_division_id, from_group_id, movement)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (season_id, row["user_id"], group["division_id"], target_division, group["id"], movement),
            )
            profile = conn.execute(
                """
                SELECT p.user_id, p.lat, p.lng, p.rating, p.current_group_id AS previous_group_id, l.city, l.region
                FROM player_profiles p
                JOIN locations l ON l.id = p.location_id
                WHERE p.user_id = ?
                """,
                (row["user_id"],),
            ).fetchone()
            players_by_division.setdefault(target_division, []).append(dict(profile))

    apply_monthly_achievements(conn, season_id, ranking_rows, promoted)
    conn.execute("UPDATE seasons SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE id = ?", (season_id,))
    name, starts_on, ends_on = next_month_season(season)
    cursor = conn.execute(
        "INSERT INTO seasons (name, starts_on, ends_on, status) VALUES (?, ?, ?, 'active')",
        (name, starts_on, ends_on),
    )
    next_season_id = cursor.lastrowid
    created = create_groups_for_season(conn, next_season_id, players_by_division)

    for history in conn.execute(
        "SELECT id, user_id, to_division_id FROM promotion_relegation_history WHERE season_id = ?",
        (season_id,),
    ).fetchall():
        group = conn.execute(
            "SELECT current_group_id FROM player_profiles WHERE user_id = ?",
            (history["user_id"],),
        ).fetchone()
        conn.execute(
            "UPDATE promotion_relegation_history SET to_group_id = ? WHERE id = ?",
            (group["current_group_id"], history["id"]),
        )

    conn.execute("UPDATE player_profiles SET xp_monthly = 0")
    return {
        "closed": True,
        "season_id": season_id,
        "next_season_id": next_season_id,
        "groups_created": sum(len(group_ids) for group_ids in created.values()),
        "promotions": len(promoted),
    }


def public_ranking_rows(rows):
    return [
        {
            key: row[key]
            for key in (
                "user_id",
                "display_name",
                "rating",
                "division_name",
                "avatar_base_image",
                "equipped_frame_name",
                "points",
                "played",
                "wins",
                "losses",
                "walkovers",
                "set_average",
                "game_average",
                "opponent_strength",
                "rank_position",
                "valid_match_ids",
                "discarded_match_ids",
                "movement_zone",
                "points_to_next_position",
                "promotion_gap_points",
                "relegation_gap_points",
                "standing_note",
            )
        }
        for row in rows
    ]


def divisions(conn):
    return rows_to_dicts(
        conn.execute(
            """
            SELECT d.*, l.scope
            FROM divisions d
            JOIN league_levels l ON l.id = d.level_id
            ORDER BY d.sort_order ASC
            """
        ).fetchall()
    )
