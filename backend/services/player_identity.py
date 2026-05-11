from backend.database import row_to_dict, rows_to_dicts, scalar
from backend.services.free_matches import free_matches_for_user
from backend.services.match_teams import player_team, team_ids, team_score_stats, winner_team


def player_match_rows(conn, user_id, limit=None):
    sql = """
        SELECT
            m.id, m.season_id, m.group_id, m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            m.status, m.source, m.created_at, m.confirmed_at,
            r.score, r.winner_id, r.loser_id, r.winner_team, r.loser_team,
            r.sets_won_winner, r.sets_won_loser, r.games_won_winner, r.games_won_loser
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.status = 'confirmed'
          AND ? IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        ORDER BY COALESCE(m.confirmed_at, m.created_at) DESC, m.id DESC
    """
    params = [user_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def rating_before_average(conn, match_id, user_ids):
    values = []
    for user_id in user_ids:
        row = conn.execute(
            "SELECT rating_before FROM rating_history WHERE match_id = ? AND user_id = ?",
            (match_id, user_id),
        ).fetchone()
        if row:
            values.append(row["rating_before"])
        else:
            rating = scalar(conn, "SELECT rating FROM player_profiles WHERE user_id = ?", (user_id,))
            if rating is not None:
                values.append(rating)
    return sum(values) / len(values) if values else 0


def player_names(conn, user_ids):
    if not user_ids:
        return ""
    placeholders = ",".join("?" for _ in user_ids)
    rows = conn.execute(
        f"SELECT display_name FROM player_profiles WHERE user_id IN ({placeholders}) ORDER BY display_name",
        tuple(user_ids),
    ).fetchall()
    return " / ".join(row["display_name"] for row in rows)


def streaks(results):
    if not results:
        return {
            "current": {"type": "none", "count": 0, "label": "Sin racha activa"},
            "best": {"type": "win", "count": 0, "label": "0 victorias"},
        }
    current_type = results[0]["result"]
    current_count = 0
    for result in results:
        if result["result"] != current_type:
            break
        current_count += 1

    best_wins = 0
    running = 0
    for result in reversed(results):
        if result["result"] == "win":
            running += 1
            best_wins = max(best_wins, running)
        else:
            running = 0
    current_noun = "victoria" if current_type == "win" else "derrota"
    return {
        "current": {
            "type": current_type,
            "count": current_count,
            "label": f"{current_count} {current_noun}{'s' if current_count != 1 else ''} seguidas",
        },
        "best": {
            "type": "win",
            "count": best_wins,
            "label": f"{best_wins} victoria{'s' if best_wins != 1 else ''}",
        },
    }


def player_styles(stats, profile):
    played = stats["played"]
    wins = stats["wins"]
    styles = []
    if wins and stats["straight_set_wins"] / wins >= 0.5:
        styles.append("Ofensivo")
    if played >= 3 and stats["win_rate"] >= 60:
        styles.append("Competidor")
    if wins and stats["three_set_wins"] / wins >= 0.35:
        styles.append("Defensivo")
    if played and stats["sets_lost"] <= max(1, stats["sets_won"] * 0.45):
        styles.append("Resistente")
    if not styles and profile["rating"] >= 1100:
        styles.append("Competidor")
    if not styles:
        styles.append("En crecimiento")
    return styles[:2]


def highlighted_achievements(conn, user_id):
    priority = ("giant_killer", "undefeated", "promotion", "top_3", "iron_player", "monthly_winner")
    placeholders = ",".join("?" for _ in priority)
    rows = rows_to_dicts(
        conn.execute(
            f"""
            SELECT a.code, a.name, a.description, ua.earned_at
            FROM achievements a
            JOIN user_achievements ua ON ua.achievement_id = a.id
            WHERE ua.user_id = ? AND a.code IN ({placeholders})
            ORDER BY ua.earned_at DESC, a.id
            LIMIT 5
            """,
            (user_id, *priority),
        ).fetchall()
    )
    return rows


def division_timeline(conn, user_id):
    return rows_to_dicts(
        conn.execute(
            """
            SELECT h.movement, h.created_at, fd.name AS from_division, td.name AS to_division
            FROM promotion_relegation_history h
            LEFT JOIN divisions fd ON fd.id = h.from_division_id
            LEFT JOIN divisions td ON td.id = h.to_division_id
            WHERE h.user_id = ?
            ORDER BY h.created_at DESC, h.id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()
    )


def player_identity(conn, user_id):
    profile = conn.execute(
        """
        SELECT p.user_id, p.display_name, p.rating, p.xp_total, p.xp_monthly,
               d.name AS division_name, g.name AS group_name,
               ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
        FROM player_profiles p
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN groups g ON g.id = p.current_group_id
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        WHERE p.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not profile:
        return {}
    profile = row_to_dict(profile)
    matches = player_match_rows(conn, user_id)
    stats = {
        "played": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "sets_won": 0,
        "sets_lost": 0,
        "games_won": 0,
        "games_lost": 0,
        "game_average": 0,
        "straight_set_wins": 0,
        "three_set_wins": 0,
    }
    results = []
    giant_killer_wins = 0
    last_matches = []
    for row in matches:
        match = dict(row)
        my_team = player_team(match, user_id)
        winning_team = winner_team(match)
        if not my_team or not winning_team:
            continue
        team_stats = team_score_stats(match, my_team)
        won = my_team == winning_team
        stats["played"] += 1
        stats["wins" if won else "losses"] += 1
        stats["sets_won"] += team_stats["sets_won"]
        stats["sets_lost"] += team_stats["sets_lost"]
        stats["games_won"] += team_stats["games_won"]
        stats["games_lost"] += team_stats["games_lost"]
        if won and team_stats["sets_lost"] == 0:
            stats["straight_set_wins"] += 1
        if won and team_stats["sets_won"] + team_stats["sets_lost"] >= 3:
            stats["three_set_wins"] += 1
        my_ids = team_ids(match, my_team)
        opponent_ids = team_ids(match, "B" if my_team == "A" else "A")
        if won and rating_before_average(conn, row["id"], opponent_ids) > rating_before_average(conn, row["id"], my_ids):
            giant_killer_wins += 1
        result = "win" if won else "loss"
        results.append({"result": result, "created_at": row["confirmed_at"] or row["created_at"]})
        if len(last_matches) < 10:
            last_matches.append(
                {
                    "id": row["id"],
                    "result": result,
                    "label": "Victoria" if won else "Derrota",
                    "score": row["score"],
                    "team": player_names(conn, my_ids),
                    "opponents": player_names(conn, opponent_ids),
                    "created_at": row["confirmed_at"] or row["created_at"],
                }
            )
    for row in free_matches_for_user(conn, user_id, limit=None):
        won = row["winner_team"] == "A"
        stats["played"] += 1
        stats["wins" if won else "losses"] += 1
        stats["sets_won"] += row["sets_won_user_team"]
        stats["sets_lost"] += row["sets_won_rival_team"]
        stats["games_won"] += row["games_won_user_team"]
        stats["games_lost"] += row["games_won_rival_team"]
        if won and row["sets_won_rival_team"] == 0:
            stats["straight_set_wins"] += 1
        if won and row["sets_won_user_team"] + row["sets_won_rival_team"] >= 3:
            stats["three_set_wins"] += 1
        result = "win" if won else "loss"
        results.append({"result": result, "created_at": row["played_on"]})
        last_matches.append(
            {
                "id": f"free-{row['id']}",
                "result": result,
                "label": "Victoria libre" if won else "Derrota libre",
                "score": row["score"],
                "team": row["team_a_label"],
                "opponents": row["team_b_label"],
                "created_at": row["played_on"],
            }
        )
    results = sorted(results, key=lambda item: item["created_at"] or "", reverse=True)
    last_matches = sorted(last_matches, key=lambda item: item["created_at"] or "", reverse=True)[:10]
    if stats["played"]:
        stats["win_rate"] = round((stats["wins"] / stats["played"]) * 100)
    stats["game_average"] = stats["games_won"] - stats["games_lost"]
    streak_data = streaks(results)
    average_position = scalar(conn, "SELECT AVG(rank_position) FROM ranking_entries WHERE user_id = ?", (user_id,))
    promotions = scalar(conn, "SELECT COUNT(*) FROM promotion_relegation_history WHERE user_id = ? AND movement = 'promotion'", (user_id,)) or 0
    relegations = scalar(conn, "SELECT COUNT(*) FROM promotion_relegation_history WHERE user_id = ? AND movement = 'relegation'", (user_id,)) or 0
    rating_evolution = rows_to_dicts(
        conn.execute(
            """
            SELECT match_id, rating_before, rating_after, delta, created_at
            FROM rating_history
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 12
            """,
            (user_id,),
        ).fetchall()
    )
    ranking_evolution = rows_to_dicts(
        conn.execute(
            """
            SELECT season_id, group_id, points, played, rank_position, computed_at
            FROM ranking_entries
            WHERE user_id = ?
            ORDER BY computed_at DESC, id DESC
            LIMIT 12
            """,
            (user_id,),
        ).fetchall()
    )
    current_ranking = ranking_evolution[0] if ranking_evolution else None
    return {
        "profile": profile,
        "current_ranking": current_ranking,
        "stats": stats,
        "advanced": {
            "current_streak": streak_data["current"],
            "best_streak": streak_data["best"],
            "average_position": round(average_position, 1) if average_position else None,
            "promotions": promotions,
            "relegations": relegations,
            "giant_killer_wins": giant_killer_wins,
        },
        "styles": player_styles(stats, profile),
        "highlighted_achievements": highlighted_achievements(conn, user_id),
        "last_matches": last_matches,
        "ranking_evolution": ranking_evolution,
        "rating_evolution": rating_evolution,
        "division_timeline": division_timeline(conn, user_id),
    }
