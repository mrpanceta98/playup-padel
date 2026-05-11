from backend.database import rows_to_dicts, scalar


DAILY_NOTIFICATION_LIMIT = 3


def notification_state(row):
    item = dict(row)
    item["status"] = "read" if item.get("read_at") else "unread"
    item["unread"] = not bool(item.get("read_at"))
    return item


def create_notification(
    conn,
    user_id,
    notification_type,
    title,
    body,
    related_type=None,
    related_id=None,
    priority=1,
    event_key=None,
    force=False,
):
    event_key = event_key or f"{notification_type}:{related_type or ''}:{related_id or ''}:{title}"
    existing_today = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ? AND event_key = ? AND date(created_at) = date('now')
        """,
        (user_id, event_key),
    )
    if existing_today:
        return None
    today_count = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ? AND date(created_at) = date('now')
        """,
        (user_id,),
    ) or 0
    if today_count >= DAILY_NOTIFICATION_LIMIT and not force:
        lowest = conn.execute(
            """
            SELECT id, priority
            FROM notifications
            WHERE user_id = ? AND date(created_at) = date('now')
            ORDER BY priority ASC, created_at ASC, id ASC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if not lowest or lowest["priority"] >= priority:
            return None
        conn.execute("DELETE FROM notifications WHERE id = ?", (lowest["id"],))
    cursor = conn.execute(
        """
        INSERT INTO notifications (user_id, type, title, body, related_type, related_id, priority, event_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, notification_type, title, body, related_type, related_id, priority, event_key),
    )
    return cursor.lastrowid


def list_notifications(conn, user_id, limit=20):
    return [
        notification_state(row)
        for row in conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE user_id = ?
            ORDER BY read_at IS NOT NULL, priority DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    ]


def unread_count(conn, user_id):
    return scalar(conn, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (user_id,)) or 0


def mark_notification_read(conn, user_id, notification_id):
    conn.execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )


def mark_all_notifications_read(conn, user_id):
    conn.execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
    )


def active_group(conn, season_id, user_id):
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


def generate_context_notifications(conn, season_id, user_id):
    from backend.services.competition import public_ranking_rows, ranking_for_group

    group = active_group(conn, season_id, user_id)
    if not group:
        return
    ranking = public_ranking_rows(ranking_for_group(conn, season_id, group["id"], persist=True))
    me = next((row for row in ranking if row["user_id"] == user_id), None)
    if me:
        if me["movement_zone"] == "promotion":
            create_notification(
                conn,
                user_id,
                "competition",
                "Estás en zona de ascenso",
                "Vas en top 3. Defiende tu posición este mes.",
                "ranking",
                season_id,
                priority=3,
                event_key=f"competition:promotion:{season_id}:{me['rank_position']}",
            )
        elif me["movement_zone"] == "relegation":
            create_notification(
                conn,
                user_id,
                "competition",
                "Estás en zona de descenso",
                "Necesitas sumar para salir de los tres últimos.",
                "ranking",
                season_id,
                priority=3,
                event_key=f"competition:relegation:{season_id}:{me['rank_position']}",
            )
        if me["rank_position"] > 3 and me.get("promotion_gap_points") and me["promotion_gap_points"] <= 3:
            create_notification(
                conn,
                user_id,
                "competition",
                "A 1 victoria de subir",
                "Una victoria puede meterte en zona de ascenso.",
                "ranking",
                season_id,
                priority=2,
                event_key=f"competition:one_win:{season_id}:{me['points']}",
            )
        if me["played"] == 9:
            create_notification(
                conn,
                user_id,
                "challenge",
                "Te falta 1 partido para completar el reto mensual",
                "Completa 10 partidos válidos y reclama la recompensa.",
                "monthly_challenge",
                season_id,
                priority=2,
                event_key=f"challenge:play10:one_left:{season_id}",
            )

    pending = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM matches
        WHERE season_id = ? AND status = 'pending_confirmation'
          AND created_by != ?
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id, user_id),
    ) or 0
    if pending:
        create_notification(
            conn,
            user_id,
            "match",
            "Tienes un resultado pendiente de confirmar",
            f"{pending} resultado{'s' if pending != 1 else ''} espera tu confirmación.",
            "match",
            season_id,
            priority=3,
            event_key=f"match:pending_confirmation:{season_id}:{pending}",
        )

    activity = conn.execute(
        """
        SELECT m.id
        FROM matches m
        WHERE m.season_id = ? AND m.group_id = ? AND m.status = 'confirmed'
          AND julianday(COALESCE(m.confirmed_at, m.created_at)) >= julianday('now', '-24 hours')
          AND ? NOT IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        ORDER BY COALESCE(m.confirmed_at, m.created_at) DESC, m.id DESC
        LIMIT 1
        """,
        (season_id, group["id"], user_id),
    ).fetchone()
    if activity:
        create_notification(
            conn,
            user_id,
            "activity",
            "Un rival cercano ha jugado un partido",
            "Hay movimiento en tu liga. Reacciona con tu próximo partido.",
            "match",
            activity["id"],
            priority=1,
            event_key=f"activity:nearby_match:{activity['id']}",
        )

    available = conn.execute(
        """
        SELECT p.user_id, p.display_name
        FROM group_members gm
        JOIN player_profiles p ON p.user_id = gm.user_id
        WHERE gm.season_id = ? AND gm.group_id = ? AND gm.user_id != ?
          AND p.available_for_play = 1
          AND julianday(p.availability_updated_at) >= julianday('now', '-24 hours')
        ORDER BY p.availability_updated_at DESC
        LIMIT 1
        """,
        (season_id, group["id"], user_id),
    ).fetchone()
    if available:
        create_notification(
            conn,
            user_id,
            "activity",
            "Nuevo jugador disponible en tu liga",
            f"{available['display_name']} está disponible para jugar.",
            "user",
            available["user_id"],
            priority=1,
            event_key=f"activity:available:{season_id}:{available['user_id']}",
        )

    last_confirmed = conn.execute(
        """
        SELECT MAX(COALESCE(confirmed_at, created_at)) AS last_played, COUNT(*) AS played
        FROM matches
        WHERE season_id = ? AND status = 'confirmed'
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id),
    ).fetchone()
    if last_confirmed and last_confirmed["played"] and last_confirmed["last_played"]:
        inactive = scalar(conn, "SELECT julianday('now') - julianday(?)", (last_confirmed["last_played"],)) or 0
        if inactive >= 3:
            create_notification(
                conn,
                user_id,
                "inactivity",
                "Llevas 3 días sin jugar",
                "Puedes perder posiciones si tu grupo sigue sumando partidos.",
                "season",
                season_id,
                priority=1,
                event_key=f"inactivity:3days:{season_id}",
            )
