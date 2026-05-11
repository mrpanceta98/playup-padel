from backend.database import row_to_dict, rows_to_dicts, scalar
from backend.services.competition import parse_score, ranking_for_group
from backend.services.gamification import grant_achievement, grant_xp
from backend.services.match_teams import first_or_none, participant_ids, player_team, team_ids, team_rating_average, winner_team
from backend.services.notifications import create_notification, list_notifications
from backend.services.rating import apply_rating_for_match


WEEKLY_MATCH_TARGET = 3
CHALLENGE_REWARD_XP = 75
WEEKLY_REWARD_XP = 125


def active_group_for_user(conn, season_id, user_id):
    return conn.execute(
        """
        SELECT g.*
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        WHERE gm.season_id = ? AND gm.user_id = ? AND gm.active = 1
        LIMIT 1
        """,
        (season_id, user_id),
    ).fetchone()


def user_name(conn, user_id):
    row = conn.execute("SELECT display_name FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
    return row["display_name"] if row else "Jugador"


def challenge_row(conn, challenge_id):
    return conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()


def ensure_challenge_participant(challenge, user_id):
    return user_id in challenge_participants(challenge)


def challenge_participants(challenge):
    return [
        user_id
        for user_id in (
            challenge["challenger_id"],
            challenge["challenger_partner_id"],
            challenge["challenged_id"],
            challenge["challenged_partner_id"],
        )
        if user_id
    ]


def challenge_team(challenge, side):
    if side == "A":
        return [user_id for user_id in (challenge["challenger_id"], challenge["challenger_partner_id"]) if user_id]
    return [user_id for user_id in (challenge["challenged_id"], challenge["challenged_partner_id"]) if user_id]


def challenge_payload(conn, row, current_user_id):
    def card(user_id):
        if not user_id:
            return None
        found = conn.execute(
            """
            SELECT p.user_id, p.display_name, p.rating, p.level_guess,
                   ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
            FROM player_profiles p
            LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
            LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
            LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
            WHERE p.user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return row_to_dict(found) if found else None

    challenger = card(row["challenger_id"])
    challenged = card(row["challenged_id"])
    challenger_partner = card(row["challenger_partner_id"])
    challenged_partner = card(row["challenged_partner_id"])
    return {
        **row_to_dict(row),
        "challenger_name": challenger["display_name"] if challenger else "",
        "challenger_rating": challenger["rating"] if challenger else 0,
        "challenged_name": challenged["display_name"] if challenged else "",
        "challenged_rating": challenged["rating"] if challenged else 0,
        "team_a": [player for player in (challenger, challenger_partner) if player],
        "team_b": [player for player in (challenged, challenged_partner) if player],
        "can_accept": row["type"] != "weekly" and row["status"] == "pending" and row["challenged_id"] == current_user_id,
        "can_submit_result": row["type"] != "weekly" and row["status"] == "accepted" and ensure_challenge_participant(row, current_user_id) and not row["match_id"],
    }


def list_challenges(conn, season_id, user_id):
    rows = conn.execute(
        """
        SELECT *
        FROM challenges
        WHERE season_id = ?
          AND ? IN (challenger_id, challenged_id, challenger_partner_id, challenged_partner_id)
        ORDER BY created_at DESC, id DESC
        """,
        (season_id, user_id),
    ).fetchall()
    return [challenge_payload(conn, row, user_id) for row in rows]


def suggested_rivals(conn, season_id, user_id, limit=5, rating_window=100, recent_days=14):
    group = active_group_for_user(conn, season_id, user_id)
    if not group:
        return []
    me = conn.execute("SELECT rating FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not me:
        return []
    pending_ids = {
        row["other_id"]
        for row in conn.execute(
            """
            SELECT CASE WHEN challenger_id = ? THEN challenged_id ELSE challenger_id END AS other_id
            FROM challenges
            WHERE season_id = ?
              AND status IN ('pending', 'accepted')
              AND ? IN (challenger_id, challenged_id, challenger_partner_id, challenged_partner_id)
            """,
            (user_id, season_id, user_id),
        ).fetchall()
    }
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                p.user_id,
                p.display_name,
                p.level_guess,
                p.rating,
                ab.image_path AS avatar_base_image,
                frame.name AS equipped_frame_name,
                l.city,
                l.region,
                ABS(p.rating - ?) AS rating_delta,
                COUNT(DISTINCT activity.id) AS active_matches,
                MAX(activity.created_at) AS latest_activity_at,
                MAX(head_to_head.created_at) AS last_played_at
            FROM group_members gm
            JOIN player_profiles p ON p.user_id = gm.user_id
            JOIN locations l ON l.id = p.location_id
            LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
            LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
            LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
            LEFT JOIN matches activity
              ON activity.season_id = gm.season_id
             AND activity.status IN ('pending_confirmation', 'confirmed', 'conflict')
             AND p.user_id IN (
                activity.player_a_id, activity.player_b_id,
                activity.team_a_player_1_id, activity.team_a_player_2_id,
                activity.team_b_player_1_id, activity.team_b_player_2_id
             )
            LEFT JOIN matches head_to_head
              ON head_to_head.season_id = gm.season_id
             AND head_to_head.status IN ('pending_confirmation', 'confirmed', 'conflict')
             AND (
                (? IN (
                    head_to_head.player_a_id, head_to_head.team_a_player_1_id, head_to_head.team_a_player_2_id
                ) AND p.user_id IN (
                    head_to_head.player_b_id, head_to_head.team_b_player_1_id, head_to_head.team_b_player_2_id
                ))
                OR
                (? IN (
                    head_to_head.player_b_id, head_to_head.team_b_player_1_id, head_to_head.team_b_player_2_id
                ) AND p.user_id IN (
                    head_to_head.player_a_id, head_to_head.team_a_player_1_id, head_to_head.team_a_player_2_id
                ))
             )
            WHERE gm.season_id = ? AND gm.group_id = ? AND gm.user_id != ? AND gm.active = 1
              AND ABS(p.rating - ?) <= ?
            GROUP BY p.user_id
            HAVING last_played_at IS NULL OR julianday(last_played_at) < julianday('now', ?)
            """,
            (me["rating"], user_id, user_id, season_id, group["id"], user_id, me["rating"], rating_window, f"-{recent_days} days"),
        ).fetchall()
    )
    filtered = [row for row in rows if row["user_id"] not in pending_ids]
    return sorted(
        filtered,
        key=lambda row: (
            -row["active_matches"],
            row["rating_delta"],
            row["display_name"],
        ),
    )[:limit]


def weekly_challenges(conn, season_id, user_id):
    valid_matches = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM matches
        WHERE season_id = ? AND status = 'confirmed'
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id),
    ) or 0
    higher_rating_wins = 0
    rows = conn.execute(
        """
        SELECT
            m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.season_id = ? AND m.status = 'confirmed'
          AND ? IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        """,
        (season_id, user_id),
    ).fetchall()
    for row in rows:
        side = player_team(row, user_id)
        if side == winner_team(row):
            my_rating = team_rating_average(conn, team_ids(row, side))
            opponent_rating = team_rating_average(conn, team_ids(row, "B" if side == "A" else "A"))
            if opponent_rating > my_rating:
                higher_rating_wins += 1
    specs = [
        {
            "key": "weekly_matches",
            "code": "weekly_matches",
            "title": f"Juega {WEEKLY_MATCH_TARGET} partidos esta semana",
            "progress": min(valid_matches, WEEKLY_MATCH_TARGET),
            "target": WEEKLY_MATCH_TARGET,
            "reward_xp": WEEKLY_REWARD_XP,
            "completed": valid_matches >= WEEKLY_MATCH_TARGET,
        },
        {
            "key": "beat_higher_rating",
            "code": "beat_higher_rating",
            "title": "Gana a un rival con mayor rating",
            "progress": min(higher_rating_wins, 1),
            "target": 1,
            "reward_xp": WEEKLY_REWARD_XP,
            "completed": higher_rating_wins >= 1,
        },
    ]
    group = active_group_for_user(conn, season_id, user_id)
    for item in specs:
        row = conn.execute(
            """
            SELECT *
            FROM challenges
            WHERE season_id = ? AND challenger_id = ? AND challenged_id = ? AND type = 'weekly' AND title = ?
            LIMIT 1
            """,
            (season_id, user_id, user_id, item["title"]),
        ).fetchone()
        if not row:
            cursor = conn.execute(
                """
                INSERT INTO challenges
                (season_id, group_id, challenger_id, challenged_id, type, status, title, description, reward_xp)
                VALUES (?, ?, ?, ?, 'weekly', 'pending', ?, ?, ?)
                """,
                (
                    season_id,
                    group["id"] if group else None,
                    user_id,
                    user_id,
                    item["title"],
                    "Reto semanal generado automaticamente por PlayUp Padel.",
                    item["reward_xp"],
                ),
            )
            row = challenge_row(conn, cursor.lastrowid)
        if item["completed"] and row["status"] != "completed":
            conn.execute("UPDATE challenges SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
            grant_xp(conn, user_id, season_id, item["reward_xp"], "challenge", item["title"])
            grant_achievement(conn, user_id, "weekly_challenger", season_id)
            create_notification(
                conn,
                user_id,
                "challenge",
                "Reto semanal completado",
                f"{item['title']}: +{item['reward_xp']} XP.",
                "challenge",
                row["id"],
            )
            row = challenge_row(conn, row["id"])
        item["challenge_id"] = row["id"]
        item["status"] = row["status"]
    return specs


def create_open_challenge(conn, season_id, challenger_id, challenged_id, title=None, description="", challenger_partner_id=None, challenged_partner_id=None):
    users = [user_id for user_id in (challenger_id, challenger_partner_id, challenged_id, challenged_partner_id) if user_id]
    if len(users) != len(set(users)):
        raise ValueError("Los cuatro jugadores del reto deben ser distintos.")
    challenger_group = active_group_for_user(conn, season_id, challenger_id)
    challenged_group = active_group_for_user(conn, season_id, challenged_id)
    if not challenger_group or not challenged_group or challenger_group["id"] != challenged_group["id"]:
        raise ValueError("Solo puedes retar a jugadores de tu grupo activo en este MVP.")
    for user_id in users:
        group = active_group_for_user(conn, season_id, user_id)
        if not group or group["id"] != challenger_group["id"]:
            raise ValueError("Todos los jugadores del reto deben pertenecer a tu grupo activo.")
    existing = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM challenges
        WHERE season_id = ?
          AND status IN ('pending', 'accepted')
          AND ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?))
        """,
        (season_id, challenger_id, challenged_id, challenged_id, challenger_id),
    )
    if existing:
        raise ValueError("Ya hay un reto abierto entre estos jugadores.")
    challenger_name = user_name(conn, challenger_id)
    default_title = f"{challenger_name} te reta a jugar"
    cursor = conn.execute(
        """
        INSERT INTO challenges
        (season_id, group_id, challenger_id, challenged_id, challenger_partner_id, challenged_partner_id,
         type, status, title, description, reward_xp)
        VALUES (?, ?, ?, ?, ?, ?, 'open', 'pending', ?, ?, ?)
        """,
        (
            season_id,
            challenger_group["id"],
            challenger_id,
            challenged_id,
            challenger_partner_id,
            challenged_partner_id,
            title or default_title,
            description,
            CHALLENGE_REWARD_XP,
        ),
    )
    challenge_id = cursor.lastrowid
    create_notification(
        conn,
        challenged_id,
        "challenge",
        "Nuevo reto recibido",
        f"{challenger_name} quiere jugar un partido competitivo contigo.",
        "challenge",
        challenge_id,
    )
    return challenge_id


def create_automatic_challenge(conn, season_id, user_id, challenged_id, challenger_partner_id=None, challenged_partner_id=None):
    challenge_id = create_open_challenge(
        conn,
        season_id,
        user_id,
        challenged_id,
        title="Reto recomendado por PlayUp Padel",
        description="Rival sugerido por rating similar dentro de tu grupo.",
        challenger_partner_id=challenger_partner_id,
        challenged_partner_id=challenged_partner_id,
    )
    conn.execute("UPDATE challenges SET type = 'automatic' WHERE id = ?", (challenge_id,))
    return challenge_id


def accept_challenge(conn, challenge_id, user_id):
    challenge = challenge_row(conn, challenge_id)
    if not challenge:
        raise ValueError("Reto no encontrado.")
    if challenge["challenged_id"] != user_id:
        raise ValueError("Solo el jugador retado puede aceptar.")
    if challenge["status"] != "pending":
        raise ValueError("Este reto ya no esta pendiente.")
    conn.execute("UPDATE challenges SET status = 'accepted', responded_at = CURRENT_TIMESTAMP WHERE id = ?", (challenge_id,))
    grant_achievement(conn, user_id, "challenge_accepted", challenge["season_id"])
    create_notification(
        conn,
        challenge["challenger_id"],
        "challenge",
        "Reto aceptado",
        f"{user_name(conn, user_id)} ha aceptado tu reto.",
        "challenge",
        challenge_id,
    )
    return challenge_id


def reject_challenge(conn, challenge_id, user_id):
    challenge = challenge_row(conn, challenge_id)
    if not challenge:
        raise ValueError("Reto no encontrado.")
    if challenge["challenged_id"] != user_id:
        raise ValueError("Solo el jugador retado puede rechazar.")
    if challenge["status"] != "pending":
        raise ValueError("Este reto ya no esta pendiente.")
    conn.execute("UPDATE challenges SET status = 'rejected', responded_at = CURRENT_TIMESTAMP WHERE id = ?", (challenge_id,))
    create_notification(
        conn,
        challenge["challenger_id"],
        "challenge",
        "Reto rechazado",
        f"{user_name(conn, user_id)} ha rechazado tu reto.",
        "challenge",
        challenge_id,
    )
    return challenge_id


def submit_challenge_result(conn, challenge_id, user_id, score, is_walkover=False):
    challenge = challenge_row(conn, challenge_id)
    if not challenge:
        raise ValueError("Reto no encontrado.")
    if not ensure_challenge_participant(challenge, user_id):
        raise ValueError("No participas en este reto.")
    if challenge["status"] != "accepted":
        raise ValueError("El reto debe estar aceptado para subir resultado.")
    if challenge["match_id"]:
        raise ValueError("Este reto ya tiene un partido asociado.")

    user_side = "A" if user_id in challenge_team(challenge, "A") else "B"
    team_a = challenge_team(challenge, user_side)
    team_b = challenge_team(challenge, "B" if user_side == "A" else "A")
    parsed = parse_score(score)
    winner_side = parsed["winner_side"]
    loser_side = "B" if winner_side == "A" else "A"
    winners = team_a if winner_side == "A" else team_b
    losers = team_b if winner_side == "A" else team_a
    cursor = conn.execute(
        """
        INSERT INTO matches
        (season_id, group_id, player_a_id, player_b_id,
         team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id,
         source, status, created_by, is_walkover)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'challenge', 'pending_confirmation', ?, ?)
        """,
        (
            challenge["season_id"],
            challenge["group_id"],
            first_or_none(team_a),
            first_or_none(team_b),
            first_or_none(team_a),
            team_a[1] if len(team_a) > 1 else None,
            first_or_none(team_b),
            team_b[1] if len(team_b) > 1 else None,
            user_id,
            int(bool(is_walkover)),
        ),
    )
    match_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO match_results
        (match_id, score, winner_id, loser_id, winner_team, loser_team, sets_won_winner, sets_won_loser,
         games_won_winner, games_won_loser, submitted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            score,
            first_or_none(winners),
            first_or_none(losers),
            winner_side,
            loser_side,
            parsed[winner_side.lower()]["sets_won"],
            parsed[loser_side.lower()]["sets_won"],
            parsed[winner_side.lower()]["games_won"],
            parsed[loser_side.lower()]["games_won"],
            user_id,
        ),
    )
    conn.execute("UPDATE challenges SET match_id = ? WHERE id = ?", (match_id, challenge_id))
    for notify_user_id in team_b:
        create_notification(
            conn,
            notify_user_id,
            "challenge",
            "Resultado de reto pendiente",
            f"{user_name(conn, user_id)} ha subido el resultado del reto. Confirma el marcador.",
            "match",
            match_id,
        )
    return match_id


def complete_challenge_for_match(conn, match_id):
    challenge = conn.execute("SELECT * FROM challenges WHERE match_id = ?", (match_id,)).fetchone()
    if not challenge or challenge["status"] == "completed":
        return None
    match = conn.execute("SELECT * FROM matches WHERE id = ? AND status = 'confirmed'", (match_id,)).fetchone()
    if not match:
        return None
    conn.execute("UPDATE challenges SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?", (challenge["id"],))
    for user_id in challenge_participants(challenge):
        grant_xp(conn, user_id, challenge["season_id"], challenge["reward_xp"], "challenge", "Reto completado", match_id)
        grant_achievement(conn, user_id, "challenge_completed", challenge["season_id"])
        create_notification(
            conn,
            user_id,
            "challenge",
            "Reto completado",
            f"Has ganado {challenge['reward_xp']} XP extra por completar el reto.",
            "challenge",
            challenge["id"],
        )
    ranking_for_group(conn, match["season_id"], match["group_id"], persist=True)
    return challenge["id"]
