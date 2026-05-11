from datetime import date, datetime

from backend.database import row_to_dict, rows_to_dicts, scalar
from backend.services.challenges import active_group_for_user, create_notification
from backend.services.competition import ranking_for_group
from backend.services.gamification import grant_achievement, grant_xp
from backend.services.free_matches import free_activity_count
from backend.services.match_teams import player_team, team_ids, team_rating_average, winner_team


MONTHLY_SPECS = [
    ("play_3", "Juega 3 partidos", "Completa 3 partidos competitivos validos este mes.", 3, 150, None, "monthly_regular"),
    ("play_5", "Juega 5 partidos", "Mantén ritmo competitivo con 5 partidos validos.", 5, 250, None, "monthly_regular"),
    ("play_10", "Completa 10 partidos validos", "Llena el cupo mensual que cuenta para ranking.", 10, 450, "season_background_may", "iron_player"),
    ("win_3", "Gana 3 partidos", "Suma 3 victorias individuales en tu grupo.", 3, 350, None, "monthly_winner"),
    ("beat_higher_pair", "Gana a una pareja con mas rating medio", "Derrota a una pareja con rating medio superior al de tu pareja.", 1, 300, "season_effect_may", "giant_killer"),
    ("promotion_zone", "Entra en zona de ascenso", "Colocate en el top 3 de tu grupo mensual.", 1, 300, "season_frame_may", "monthly_podium"),
    ("confirm_all", "Confirma todos tus resultados del mes", "No dejes ningun resultado pendiente de tu confirmacion.", 1, 200, None, "monthly_clean_sheet"),
]


def seed_monthly_challenges(conn, season_id):
    for sort_order, (code, title, description, target, reward_xp, item_code, achievement_code) in enumerate(MONTHLY_SPECS, start=1):
        item_id = None
        if item_code:
            item = conn.execute("SELECT id FROM avatar_items WHERE code = ?", (item_code,)).fetchone()
            item_id = item["id"] if item else None
        conn.execute(
            """
            INSERT INTO monthly_challenges
            (season_id, code, title, description, target, reward_xp, reward_avatar_item_id,
             reward_achievement_code, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(season_id, code) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                target = excluded.target,
                reward_xp = excluded.reward_xp,
                reward_avatar_item_id = excluded.reward_avatar_item_id,
                reward_achievement_code = excluded.reward_achievement_code,
                sort_order = excluded.sort_order,
                is_active = 1
            """,
            (season_id, code, title, description, target, reward_xp, item_id, achievement_code, sort_order),
        )


def user_monthly_stats(conn, season_id, user_id):
    group = active_group_for_user(conn, season_id, user_id)
    ranking_row = None
    if group:
        ranking = ranking_for_group(conn, season_id, group["id"], persist=True)
        ranking_row = next((row for row in ranking if row["user_id"] == user_id), None)
    official_played = ranking_row["played"] if ranking_row else 0
    free_played = free_activity_count(conn, season_id, user_id)
    played = official_played + free_played
    wins = ranking_row["wins"] if ranking_row else 0
    in_promotion = bool(ranking_row and ranking_row["movement_zone"] == "promotion")
    higher_pair_wins = count_higher_pair_wins(conn, season_id, user_id)
    pending_confirmations = pending_confirmations_for_user(conn, season_id, user_id)
    has_any_result = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM matches
        WHERE season_id = ? AND status IN ('pending_confirmation', 'confirmed', 'conflict')
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id),
    ) or 0
    return {
        "play_3": played,
        "play_5": played,
        "play_10": played,
        "win_3": wins,
        "beat_higher_pair": higher_pair_wins,
        "promotion_zone": 1 if in_promotion else 0,
        "confirm_all": 1 if has_any_result and pending_confirmations == 0 else 0,
    }


def count_higher_pair_wins(conn, season_id, user_id):
    total = 0
    rows = conn.execute(
        """
        SELECT m.*, r.winner_team, r.loser_team
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.season_id = ? AND m.status = 'confirmed'
          AND ? IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        """,
        (season_id, user_id),
    ).fetchall()
    for row in rows:
        my_side = player_team(row, user_id)
        if my_side != winner_team(row):
            continue
        other_side = "B" if my_side == "A" else "A"
        if team_rating_average(conn, team_ids(row, other_side)) > team_rating_average(conn, team_ids(row, my_side)):
            total += 1
    return total


def pending_confirmations_for_user(conn, season_id, user_id):
    rows = conn.execute(
        """
        SELECT *
        FROM matches
        WHERE season_id = ? AND status = 'pending_confirmation'
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id),
    ).fetchall()
    pending = 0
    for row in rows:
        creator_side = player_team(row, row["created_by"])
        my_side = player_team(row, user_id)
        if user_id != row["created_by"] and my_side and my_side != creator_side:
            pending += 1
    return pending


def list_monthly_challenges(conn, season, user_id):
    seed_monthly_challenges(conn, season["id"])
    stats = user_monthly_stats(conn, season["id"], user_id)
    rows = conn.execute(
        """
        SELECT mc.*, ai.name AS reward_item_name, ai.rarity AS reward_item_rarity, ai.image_path AS reward_item_image,
               umc.status AS user_status, umc.claimed_at
        FROM monthly_challenges mc
        LEFT JOIN avatar_items ai ON ai.id = mc.reward_avatar_item_id
        LEFT JOIN user_monthly_challenges umc ON umc.monthly_challenge_id = mc.id AND umc.user_id = ?
        WHERE mc.season_id = ? AND mc.is_active = 1
        ORDER BY mc.sort_order ASC
        """,
        (user_id, season["id"]),
    ).fetchall()
    items = []
    for row in rows:
        progress = min(stats.get(row["code"], 0), row["target"])
        completed = progress >= row["target"]
        status = row["user_status"] or ("completed" if completed else "pending")
        if status != "claimed" and completed:
            status = "completed"
        conn.execute(
            """
            INSERT INTO user_monthly_challenges (user_id, monthly_challenge_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, monthly_challenge_id) DO UPDATE SET
                status = CASE
                    WHEN user_monthly_challenges.status = 'claimed' THEN 'claimed'
                    WHEN excluded.status = 'completed' THEN 'completed'
                    ELSE user_monthly_challenges.status
                END
            """,
            (user_id, row["id"], status),
        )
        item = row_to_dict(row)
        item.update(
            {
                "progress": progress,
                "completed": completed,
                "status": status,
                "time_remaining": time_remaining_label(season["ends_on"]),
                "reward_label": reward_label(row),
            }
        )
        items.append(item)
    return items


def claim_monthly_challenge(conn, season, user_id, monthly_challenge_id):
    challenges = {item["id"]: item for item in list_monthly_challenges(conn, season, user_id)}
    item = challenges.get(monthly_challenge_id)
    if not item:
        raise ValueError("Reto mensual no encontrado.")
    if item["status"] == "claimed":
        raise ValueError("Este reto ya esta reclamado.")
    if not item["completed"]:
        raise ValueError("Aun no has completado este reto.")
    grant_xp(conn, user_id, season["id"], item["reward_xp"], "monthly_challenge", item["title"])
    if item["reward_achievement_code"]:
        grant_achievement(conn, user_id, item["reward_achievement_code"], season["id"])
    if item["reward_avatar_item_id"]:
        already_unlocked = scalar(
            conn,
            "SELECT COUNT(*) FROM user_avatar_items WHERE user_id = ? AND avatar_item_id = ?",
            (user_id, item["reward_avatar_item_id"]),
        )
        conn.execute(
            """
            INSERT INTO user_avatar_items (user_id, avatar_item_id, unlocked_at, equipped)
            VALUES (?, ?, CURRENT_TIMESTAMP, 0)
            ON CONFLICT(user_id, avatar_item_id) DO UPDATE SET unlocked_at = COALESCE(user_avatar_items.unlocked_at, CURRENT_TIMESTAMP)
            """,
            (user_id, item["reward_avatar_item_id"]),
        )
        if not already_unlocked:
            reward_item_name = scalar(conn, "SELECT name FROM avatar_items WHERE id = ?", (item["reward_avatar_item_id"],))
            create_notification(
                conn,
                user_id,
                "avatar_unlock",
                "Nuevo item desbloqueado",
                f"{reward_item_name} ya esta disponible en tu avatar.",
                "avatar_item",
                item["reward_avatar_item_id"],
            )
    conn.execute(
        """
        UPDATE user_monthly_challenges
        SET status = 'claimed', claimed_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND monthly_challenge_id = ?
        """,
        (user_id, monthly_challenge_id),
    )
    create_notification(
        conn,
        user_id,
        "monthly_challenge",
        "Reto mensual reclamado",
        f"{item['title']}: +{item['reward_xp']} XP.",
        "monthly_challenge",
        monthly_challenge_id,
    )
    return {
        "type": "challenge_reward",
        "title": "Reto del mes completado",
        "message": item["title"],
        "xp_gained": item["reward_xp"],
        "reward_item": item["reward_item_name"],
        "achievement": item["reward_achievement_code"],
    }


def time_remaining_label(ends_on):
    end = datetime.strptime(ends_on, "%Y-%m-%d").date()
    days = max(0, (end - date.today()).days)
    return f"{days} dias restantes" if days != 1 else "1 dia restante"


def reward_label(row):
    parts = [f"+{row['reward_xp']} XP"]
    if row["reward_item_name"]:
        parts.append(row["reward_item_name"])
    if row["reward_achievement_code"]:
        parts.append("insignia")
    return " · ".join(parts)
