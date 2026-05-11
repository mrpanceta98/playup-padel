from backend.database import row_to_dict, rows_to_dicts, scalar
from backend.services.challenges import active_group_for_user, create_automatic_challenge, create_notification, suggested_rivals, user_name


def touch_player_activity(conn, user_id):
    conn.execute("UPDATE player_profiles SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))


def player_card(row):
    item = row_to_dict(row)
    item["available_for_play"] = bool(item.get("available_for_play"))
    return item


def availability_status(conn, user_id):
    row = conn.execute(
        """
        SELECT available_for_play, availability_updated_at, last_active_at
        FROM player_profiles
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return {"available": False, "availability_updated_at": None, "last_active_at": None}
    return {
        "available": bool(row["available_for_play"]),
        "availability_updated_at": row["availability_updated_at"],
        "last_active_at": row["last_active_at"],
    }


def set_player_availability(conn, season_id, user_id, available, message=""):
    group = active_group_for_user(conn, season_id, user_id)
    if not group:
        raise ValueError("No tienes grupo activo.")
    conn.execute(
        """
        UPDATE player_profiles
        SET available_for_play = ?, availability_updated_at = CURRENT_TIMESTAMP, last_active_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (1 if available else 0, user_id),
    )
    if available:
        existing = conn.execute(
            """
            SELECT id
            FROM match_requests
            WHERE season_id = ? AND owner_id = ? AND status = 'open'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (season_id, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE match_requests
                SET message = ?, updated_at = CURRENT_TIMESTAMP, expires_at = datetime('now', '+6 hours')
                WHERE id = ?
                """,
                (message or "Busco partido competitivo.", existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO match_requests (season_id, group_id, owner_id, status, message, expires_at)
                VALUES (?, ?, ?, 'open', ?, datetime('now', '+6 hours'))
                """,
                (season_id, group["id"], user_id, message or "Busco partido competitivo."),
            )
    else:
        conn.execute(
            """
            UPDATE match_requests
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE season_id = ? AND owner_id = ? AND status = 'open'
            """,
            (season_id, user_id),
        )
    return availability_status(conn, user_id)


def active_players_48h(conn, season_id, user_id, limit=8):
    group = active_group_for_user(conn, season_id, user_id)
    if not group:
        return []
    rows = conn.execute(
        """
        SELECT
            p.user_id, p.display_name, p.level_guess, p.rating, p.available_for_play,
            p.availability_updated_at, p.last_active_at, d.name AS division_name,
            ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name,
            l.city, l.region
        FROM group_members gm
        JOIN player_profiles p ON p.user_id = gm.user_id
        JOIN locations l ON l.id = p.location_id
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        WHERE gm.season_id = ? AND gm.group_id = ? AND gm.active = 1 AND gm.user_id != ?
          AND p.last_active_at IS NOT NULL
          AND julianday(p.last_active_at) >= julianday('now', '-48 hours')
        ORDER BY p.available_for_play DESC, p.last_active_at DESC, ABS(p.rating - (
            SELECT rating FROM player_profiles WHERE user_id = ?
        )) ASC
        LIMIT ?
        """,
        (season_id, group["id"], user_id, user_id, limit),
    ).fetchall()
    return [player_card(row) for row in rows]


def suggested_partner(conn, season_id, user_id):
    group = active_group_for_user(conn, season_id, user_id)
    if not group:
        return None
    row = conn.execute(
        """
        SELECT
            p.user_id, p.display_name, p.level_guess, p.rating, p.available_for_play,
            p.availability_updated_at, p.last_active_at, d.name AS division_name,
            ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name,
            l.city, l.region,
            ABS(p.rating - me.rating) AS rating_delta
        FROM group_members gm
        JOIN player_profiles p ON p.user_id = gm.user_id
        JOIN player_profiles me ON me.user_id = ?
        JOIN locations l ON l.id = p.location_id
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        WHERE gm.season_id = ? AND gm.group_id = ? AND gm.active = 1 AND gm.user_id != ?
        ORDER BY p.available_for_play DESC,
                 CASE WHEN p.last_active_at IS NOT NULL AND julianday(p.last_active_at) >= julianday('now', '-48 hours') THEN 0 ELSE 1 END,
                 rating_delta ASC,
                 p.display_name ASC
        LIMIT 1
        """,
        (user_id, season_id, group["id"], user_id),
    ).fetchone()
    return player_card(row) if row else None


def play_now_recommendation(conn, season_id, user_id):
    partner = suggested_partner(conn, season_id, user_id)
    rivals = suggested_rivals(conn, season_id, user_id, limit=3)
    if partner:
        rivals = [rival for rival in rivals if rival["user_id"] != partner["user_id"]]
    if len(rivals) < 3:
        active_ids = {rival["user_id"] for rival in rivals}
        if partner:
            active_ids.add(partner["user_id"])
        for player in active_players_48h(conn, season_id, user_id, limit=8):
            if player["user_id"] not in active_ids:
                rivals.append(player)
                active_ids.add(player["user_id"])
            if len(rivals) >= 3:
                break
    return {
        "availability": availability_status(conn, user_id),
        "suggested_partner": partner,
        "recommended_rivals": rivals[:3],
        "active_players_48h": active_players_48h(conn, season_id, user_id, limit=8),
        "open_match_requests": list_match_requests(conn, season_id, user_id),
    }


def quick_match_selection(conn, season_id, user_id, partner_id=None, rival_ids=None):
    recommendation = play_now_recommendation(conn, season_id, user_id)
    partner = recommendation.get("suggested_partner")
    rivals = recommendation.get("recommended_rivals", [])
    if partner_id:
        partner = next((player for player in [partner, *recommendation["active_players_48h"]] if player and player["user_id"] == partner_id), None)
    selected_rivals = []
    requested_rivals = [int(item) for item in (rival_ids or []) if item]
    if requested_rivals:
        candidates = {player["user_id"]: player for player in [*rivals, *recommendation["active_players_48h"]]}
        selected_rivals = [candidates[user_id] for user_id in requested_rivals if user_id in candidates]
    if len(selected_rivals) < 2:
        selected_rivals = rivals[:2]
    can_create = bool(partner and len(selected_rivals) >= 2)
    return {
        "can_create": can_create,
        "reason": "" if can_create else "No hay suficientes jugadores disponibles",
        "partner": partner,
        "rivals": selected_rivals[:2],
        "play_now": recommendation,
    }


def create_quick_play_now_match(conn, season_id, user_id, partner_id=None, rival_ids=None):
    selection = quick_match_selection(conn, season_id, user_id, partner_id, rival_ids)
    if not selection["can_create"]:
        raise ValueError(selection["reason"])
    partner = selection["partner"]
    rivals = selection["rivals"]
    challenge_id = create_automatic_challenge(
        conn,
        season_id,
        user_id,
        int(rivals[0]["user_id"]),
        int(partner["user_id"]),
        int(rivals[1]["user_id"]),
    )
    conn.execute(
        "UPDATE challenges SET title = 'Partido creado desde Jugar ahora', description = 'Propuesta 2v2 generada automaticamente por PlayUp Padel.' WHERE id = ?",
        (challenge_id,),
    )
    me = conn.execute(
        """
        SELECT p.user_id, p.display_name, p.level_guess, p.rating, p.available_for_play,
               d.name AS division_name, ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
        FROM player_profiles p
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        WHERE p.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    team_a = [player_card(me), partner]
    team_b = rivals
    return {
        "challenge_id": challenge_id,
        "team_a": team_a,
        "team_b": team_b,
        "summary": f"Tú + {partner['display_name']} vs {rivals[0]['display_name']} + {rivals[1]['display_name']}",
    }


def list_match_requests(conn, season_id, user_id):
    group = active_group_for_user(conn, season_id, user_id)
    if not group:
        return []
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                mr.*,
                owner.display_name AS owner_name,
                owner.rating AS owner_rating,
                owner.level_guess AS owner_level,
                owner.available_for_play AS owner_available,
                joined.display_name AS joined_name,
                joined.rating AS joined_rating,
                joined.level_guess AS joined_level
            FROM match_requests mr
            JOIN player_profiles owner ON owner.user_id = mr.owner_id
            LEFT JOIN player_profiles joined ON joined.user_id = mr.joined_by_id
            WHERE mr.season_id = ? AND mr.group_id = ?
              AND mr.status IN ('open', 'filled')
              AND (mr.expires_at IS NULL OR julianday(mr.expires_at) >= julianday('now'))
            ORDER BY CASE WHEN mr.owner_id = ? THEN 0 ELSE 1 END, mr.created_at DESC
            LIMIT 12
            """,
            (season_id, group["id"], user_id),
        ).fetchall()
    )
    for row in rows:
        row["can_join"] = row["status"] == "open" and row["owner_id"] != user_id
        row["owner"] = {
            "user_id": row["owner_id"],
            "display_name": row["owner_name"],
            "rating": row["owner_rating"],
            "level_guess": row["owner_level"],
            "available_for_play": bool(row["owner_available"]),
        }
        row["joined"] = {
            "user_id": row["joined_by_id"],
            "display_name": row["joined_name"],
            "rating": row["joined_rating"],
            "level_guess": row["joined_level"],
        } if row["joined_by_id"] else None
    return rows


def join_match_request(conn, request_id, user_id):
    request = conn.execute("SELECT * FROM match_requests WHERE id = ?", (request_id,)).fetchone()
    if not request:
        raise ValueError("Solicitud no encontrada.")
    if request["status"] != "open":
        raise ValueError("Esta solicitud ya no esta abierta.")
    if request["owner_id"] == user_id:
        raise ValueError("Ya eres quien busca partido.")
    group = active_group_for_user(conn, request["season_id"], user_id)
    if not group or group["id"] != request["group_id"]:
        raise ValueError("Solo puedes unirte a solicitudes de tu grupo.")
    conn.execute(
        """
        UPDATE match_requests
        SET joined_by_id = ?, status = 'filled', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user_id, request_id),
    )
    create_notification(
        conn,
        request["owner_id"],
        "match_request",
        "Alguien se une a tu partido",
        f"{user_name(conn, user_id)} se ha unido a tu busqueda de partido.",
        "match_request",
        request_id,
    )
    create_notification(
        conn,
        user_id,
        "match_request",
        "Te has unido a un partido",
        f"Has avisado a {user_name(conn, request['owner_id'])} de que quieres jugar.",
        "match_request",
        request_id,
    )
    return request_id
