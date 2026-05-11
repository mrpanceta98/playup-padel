import secrets
from datetime import date

from backend.database import row_to_dict, rows_to_dicts, scalar
from backend.services.competition import parse_score
from backend.services.gamification import XP_LOSS, XP_PLAY_VALID, XP_WIN, apply_match_xp, grant_achievement, grant_xp
from backend.services.match_teams import first_or_none
from backend.services.rating import apply_rating_for_match


XP_INVITER_SIGNUP = 120
XP_INVITED_WELCOME = 100


def create_external_player(conn, created_by, display_name, club_name=""):
    name = (display_name or "").strip()
    if not name:
        raise ValueError("El nombre del jugador externo es obligatorio.")
    cursor = conn.execute(
        """
        INSERT INTO external_players (display_name, club_name, created_by)
        VALUES (?, ?, ?)
        """,
        (name, (club_name or "").strip(), created_by),
    )
    return cursor.lastrowid


def link_external_player(conn, external_player_id, linked_user_id, requester_id=None):
    row = conn.execute("SELECT * FROM external_players WHERE id = ?", (external_player_id,)).fetchone()
    if not row:
        raise ValueError("Jugador externo no encontrado.")
    user_exists = scalar(conn, "SELECT COUNT(*) FROM users WHERE id = ?", (linked_user_id,))
    if not user_exists:
        raise ValueError("Usuario real no encontrado.")
    if requester_id and row["created_by"] != requester_id:
        requester = conn.execute("SELECT role FROM users WHERE id = ?", (requester_id,)).fetchone()
        if not requester or requester["role"] != "admin":
            raise ValueError("No puedes vincular este jugador externo.")
    conn.execute(
        """
        UPDATE external_players
        SET linked_user_id = ?, linked_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (linked_user_id, external_player_id),
    )
    return row_to_dict(conn.execute("SELECT * FROM external_players WHERE id = ?", (external_player_id,)).fetchone())


def free_match_external_ids(row):
    return [row["partner_external_player_id"], row["rival_1_external_player_id"], row["rival_2_external_player_id"]]


def generate_free_match_invitations(conn, free_match_id, invited_by, base_url=""):
    row = conn.execute("SELECT * FROM free_matches WHERE id = ?", (free_match_id,)).fetchone()
    if not row or row["user_id"] != invited_by:
        raise ValueError("Partido libre no encontrado.")
    invitations = []
    for external_player_id in free_match_external_ids(row):
        existing = conn.execute(
            """
            SELECT fmi.*, ep.display_name AS external_player_name
            FROM free_match_invitations fmi
            JOIN external_players ep ON ep.id = fmi.external_player_id
            WHERE fmi.free_match_id = ? AND fmi.external_player_id = ?
            """,
            (free_match_id, external_player_id),
        ).fetchone()
        if existing:
            invitation = row_to_dict(existing)
        else:
            token = secrets.token_urlsafe(32)
            conn.execute(
                """
                INSERT INTO free_match_invitations (free_match_id, external_player_id, invited_by, token)
                VALUES (?, ?, ?, ?)
                """,
                (free_match_id, external_player_id, invited_by, token),
            )
            invitation = row_to_dict(
                conn.execute(
                    """
                    SELECT fmi.*, ep.display_name AS external_player_name
                    FROM free_match_invitations fmi
                    JOIN external_players ep ON ep.id = fmi.external_player_id
                    WHERE fmi.token = ?
                    """,
                    (token,),
                ).fetchone()
            )
        invitation["url"] = f"{base_url.rstrip('/')}/invite/{invitation['token']}" if base_url else f"/invite/{invitation['token']}"
        invitations.append(invitation)
    return invitations


def invitation_context(conn, token):
    row = conn.execute(
        """
        SELECT
            fmi.*, fm.score, fm.played_on, fm.club_name, fm.winner_team, fm.official_match_id,
            ep.display_name AS external_player_name,
            p.display_name AS inviter_name
        FROM free_match_invitations fmi
        JOIN free_matches fm ON fm.id = fmi.free_match_id
        JOIN external_players ep ON ep.id = fmi.external_player_id
        JOIN player_profiles p ON p.user_id = fmi.invited_by
        WHERE fmi.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        raise ValueError("Invitacion no encontrada.")
    return row_to_dict(row)


def accept_free_match_invitation(conn, token, user_id):
    invitation = conn.execute("SELECT * FROM free_match_invitations WHERE token = ?", (token,)).fetchone()
    if not invitation:
        raise ValueError("Invitacion no encontrada.")
    if invitation["accepted_at"] and invitation["registered_user_id"] and invitation["registered_user_id"] != user_id:
        raise ValueError("Esta invitacion ya fue utilizada.")
    external = link_external_player(conn, invitation["external_player_id"], user_id)
    if not invitation["accepted_at"]:
        season_id = scalar(conn, "SELECT season_id FROM free_matches WHERE id = ?", (invitation["free_match_id"],))
        grant_xp(conn, invitation["invited_by"], season_id, XP_INVITER_SIGNUP, "invitation", "Jugador invitado registrado")
        grant_xp(conn, user_id, season_id, XP_INVITED_WELCOME, "invitation", "Bienvenida por invitacion")
    conn.execute(
        """
        UPDATE free_match_invitations
        SET registered_user_id = ?, accepted_at = COALESCE(accepted_at, CURRENT_TIMESTAMP)
        WHERE id = ?
        """,
        (user_id, invitation["id"]),
    )
    official_match_id = try_convert_free_match_to_official(conn, invitation["free_match_id"])
    return {"external_player": external, "official_match_id": official_match_id}


def try_convert_free_match_to_official(conn, free_match_id):
    row = conn.execute("SELECT * FROM free_matches WHERE id = ?", (free_match_id,)).fetchone()
    if not row or row["official_match_id"]:
        return row["official_match_id"] if row else None
    external_rows = {
        item["id"]: item
        for item in conn.execute(
            "SELECT * FROM external_players WHERE id IN (?, ?, ?)",
            (row["partner_external_player_id"], row["rival_1_external_player_id"], row["rival_2_external_player_id"]),
        ).fetchall()
    }
    linked_ids = [external_rows[external_id]["linked_user_id"] for external_id in free_match_external_ids(row)]
    if any(not linked_id for linked_id in linked_ids):
        return None
    team_a = [row["user_id"], linked_ids[0]]
    team_b = [linked_ids[1], linked_ids[2]]
    group = conn.execute(
        """
        SELECT gm.group_id, g.division_id
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        WHERE gm.season_id = ? AND gm.user_id = ? AND gm.active = 1
        ORDER BY gm.id LIMIT 1
        """,
        (row["season_id"], row["user_id"]),
    ).fetchone()
    if not group:
        return None
    for player_id in team_a + team_b:
        ensure_user_in_group(conn, row["season_id"], group["group_id"], group["division_id"], player_id)
    winner_side = row["winner_team"]
    loser_side = "B" if winner_side == "A" else "A"
    winners = team_a if winner_side == "A" else team_b
    losers = team_b if winner_side == "A" else team_a
    cursor = conn.execute(
        """
        INSERT INTO matches
        (season_id, group_id, player_a_id, player_b_id,
         team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id,
         source, status, created_by, confirmed_at, counts_for_ranking)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'free_conversion', 'confirmed', ?, CURRENT_TIMESTAMP, 1)
        """,
        (
            row["season_id"],
            group["group_id"],
            team_a[0],
            team_b[0],
            team_a[0],
            team_a[1],
            team_b[0],
            team_b[1],
            row["user_id"],
        ),
    )
    match_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO match_results
        (match_id, score, winner_id, loser_id, winner_team, loser_team, sets_won_winner, sets_won_loser,
         games_won_winner, games_won_loser, submitted_by, confirmed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            row["score"],
            first_or_none(winners),
            first_or_none(losers),
            winner_side,
            loser_side,
            row["sets_won_user_team"] if winner_side == "A" else row["sets_won_rival_team"],
            row["sets_won_rival_team"] if winner_side == "A" else row["sets_won_user_team"],
            row["games_won_user_team"] if winner_side == "A" else row["games_won_rival_team"],
            row["games_won_rival_team"] if winner_side == "A" else row["games_won_user_team"],
            row["user_id"],
            linked_ids[1],
        ),
    )
    conn.execute("UPDATE free_matches SET official_match_id = ? WHERE id = ?", (match_id, free_match_id))
    apply_match_xp(conn, match_id)
    apply_rating_for_match(conn, match_id)
    return match_id


def ensure_user_in_group(conn, season_id, group_id, division_id, user_id):
    conn.execute(
        """
        INSERT OR IGNORE INTO group_members (group_id, user_id, season_id, active)
        VALUES (?, ?, ?, 1)
        """,
        (group_id, user_id, season_id),
    )
    conn.execute(
        """
        UPDATE player_profiles
        SET current_group_id = ?, current_division_id = ?
        WHERE user_id = ?
        """,
        (group_id, division_id, user_id),
    )


def create_free_match(conn, season_id, user_id, payload):
    partner_id = create_external_player(conn, user_id, payload.get("partner_external_name"), payload.get("club_name", ""))
    rival_1_id = create_external_player(conn, user_id, payload.get("rival_1_external_name"), payload.get("club_name", ""))
    rival_2_id = create_external_player(conn, user_id, payload.get("rival_2_external_name"), payload.get("club_name", ""))
    score = (payload.get("score") or "").strip()
    parsed = parse_score(score)
    winner_side = parsed["winner_side"]
    loser_side = "B" if winner_side == "A" else "A"
    cursor = conn.execute(
        """
        INSERT INTO free_matches
        (season_id, user_id, partner_external_player_id, rival_1_external_player_id, rival_2_external_player_id,
         club_name, played_on, score, winner_team, sets_won_user_team, sets_won_rival_team,
         games_won_user_team, games_won_rival_team)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            season_id,
            user_id,
            partner_id,
            rival_1_id,
            rival_2_id,
            (payload.get("club_name") or "").strip(),
            payload.get("played_on") or date.today().isoformat(),
            score,
            winner_side,
            parsed["a"]["sets_won"],
            parsed["b"]["sets_won"],
            parsed["a"]["games_won"],
            parsed["b"]["games_won"],
        ),
    )
    free_match_id = cursor.lastrowid
    xp_gained = apply_free_match_xp(conn, season_id, user_id, free_match_id, winner_side == "A")
    return {
        "free_match_id": free_match_id,
        "external_player_ids": [partner_id, rival_1_id, rival_2_id],
        "winner_team": winner_side,
        "loser_team": loser_side,
        "xp_gained": xp_gained,
        "invite_message": "Invita a estos jugadores para convertirlo en partido oficial.",
    }


def apply_free_match_xp(conn, season_id, user_id, free_match_id, won):
    existing = scalar(
        conn,
        "SELECT COUNT(*) FROM xp_transactions WHERE user_id = ? AND kind = 'free_match' AND reason = ?",
        (user_id, f"Partido libre #{free_match_id}"),
    )
    if existing:
        return 0
    xp_gained = XP_PLAY_VALID + (XP_WIN if won else XP_LOSS)
    grant_xp(conn, user_id, season_id, XP_PLAY_VALID, "free_match", f"Partido libre #{free_match_id}")
    grant_xp(conn, user_id, season_id, XP_WIN if won else XP_LOSS, "free_match", "Victoria partido libre" if won else "Derrota partido libre")
    grant_achievement(conn, user_id, "debut", season_id)
    return xp_gained


def free_matches_for_user(conn, user_id, limit=20):
    sql = """
        SELECT
            fm.*,
            partner.display_name AS partner_external_name,
            partner.linked_user_id AS partner_linked_user_id,
            r1.display_name AS rival_1_external_name,
            r1.linked_user_id AS rival_1_linked_user_id,
            r2.display_name AS rival_2_external_name,
            r2.linked_user_id AS rival_2_linked_user_id
        FROM free_matches fm
        JOIN external_players partner ON partner.id = fm.partner_external_player_id
        JOIN external_players r1 ON r1.id = fm.rival_1_external_player_id
        JOIN external_players r2 ON r2.id = fm.rival_2_external_player_id
        WHERE fm.user_id = ?
        ORDER BY fm.played_on DESC, fm.id DESC
    """
    params = [user_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = rows_to_dicts(conn.execute(sql, params).fetchall())
    for row in rows:
        row["result"] = "win" if row["winner_team"] == "A" else "loss"
        row["label"] = "Victoria libre" if row["winner_team"] == "A" else "Derrota libre"
        row["team_a_label"] = f"Tu + {row['partner_external_name']}"
        row["team_b_label"] = f"{row['rival_1_external_name']} + {row['rival_2_external_name']}"
        invitations = rows_to_dicts(
            conn.execute(
                """
                SELECT id, external_player_id, token, registered_user_id, accepted_at, created_at
                FROM free_match_invitations
                WHERE free_match_id = ?
                ORDER BY id
                """,
                (row["id"],),
            ).fetchall()
        )
        row["invitations"] = invitations
    return rows


def free_activity_count(conn, season_id, user_id):
    return scalar(
        conn,
        "SELECT COUNT(*) FROM free_matches WHERE season_id = ? AND user_id = ?",
        (season_id, user_id),
    ) or 0
