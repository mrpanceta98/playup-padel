from datetime import date

from backend.auth import hash_password
from backend.database import scalar
from backend.schema import init_schema
from backend.services.competition import parse_score
from backend.services.division_structure import ensure_division_structure, lowest_division_id, migrate_initial_regional_starters_to_lowest
from backend.services.gamification import apply_match_xp, ensure_all_user_avatars, ensure_user_avatar, seed_achievements
from backend.services.grouping import create_groups_for_season
from backend.services.monthly_challenges import seed_monthly_challenges
from backend.services.rating import apply_rating_for_match


LOCATIONS = [
    ("Madrid", "Madrid", 40.4168, -3.7038),
    ("Alcobendas", "Madrid", 40.5373, -3.6372),
    ("Getafe", "Madrid", 40.3083, -3.7327),
    ("Barcelona", "Cataluna", 41.3874, 2.1686),
    ("Sabadell", "Cataluna", 41.5463, 2.1086),
    ("Valencia", "Comunidad Valenciana", 39.4699, -0.3763),
    ("Sevilla", "Andalucia", 37.3891, -5.9845),
    ("Malaga", "Andalucia", 36.7213, -4.4214),
]

CLUBS = ["Central Padel", "Urban Padel Club", "Arena Smash", "Padel Norte", "Racket House", "Club Deportivo Sur"]

PLAYERS = [
    "Aitor Martin",
    "Lucia Rivas",
    "Nora Vidal",
    "Bruno Sanz",
    "Marta Soler",
    "Iker Prieto",
    "Clara Gomez",
    "Hugo Ferrer",
    "Paula Cano",
    "Dani Torres",
    "Irene Bosch",
    "Leo Molina",
    "Sara Pascual",
    "Marcos Gil",
    "Elena Ruiz",
    "Guille Navarro",
    "Julia Ramos",
    "Tomas Vega",
    "Carmen Lara",
    "Adrian Mora",
    "Vera Castillo",
    "Mario Pons",
    "Alba Ortega",
    "Ruben Leon",
]


def slug(text):
    return ".".join(text.lower().split())


def init_data(conn):
    init_schema(conn)
    seed_achievements(conn)
    ensure_division_structure(conn)
    migrate_initial_regional_starters_to_lowest(conn)
    if scalar(conn, "SELECT COUNT(*) FROM users"):
        ensure_beta_profile_integrity(conn)
        ensure_all_user_avatars(conn)
        active = conn.execute("SELECT id FROM seasons WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        if active:
            seed_monthly_challenges(conn, active["id"])
        seed_activation_state(conn)
        conn.commit()
        return

    location_ids = {}
    for city, region, lat, lng in LOCATIONS:
        cursor = conn.execute(
            "INSERT INTO locations (city, region, lat, lng) VALUES (?, ?, ?, ?)",
            (city, region, lat, lng),
        )
        location_ids[city] = cursor.lastrowid

    club_ids = []
    for index, club in enumerate(CLUBS):
        city = LOCATIONS[index % len(LOCATIONS)][0]
        cursor = conn.execute("INSERT INTO clubs (name, location_id) VALUES (?, ?)", (club, location_ids[city]))
        club_ids.append(cursor.lastrowid)

    season_cursor = conn.execute(
        "INSERT INTO seasons (name, starts_on, ends_on, status) VALUES ('Mayo 2026', '2026-05-01', '2026-05-31', 'active')"
    )
    season_id = season_cursor.lastrowid
    lowest_division = lowest_division_id(conn)

    admin_cursor = conn.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'admin')",
        ("admin@playup.local", hash_password("admin123")),
    )
    admin_id = admin_cursor.lastrowid
    conn.execute(
        """
        INSERT INTO player_profiles
        (user_id, display_name, gender, location_id, club_id, level_guess, lat, lng, current_division_id, rating, xp_total, availability_text)
        VALUES (?, 'Admin PlayUp', 'male', ?, ?, 'Avanzado', 40.4168, -3.7038, ?, 1200, 0, 'Gestión interna')
        """,
        (admin_id, location_ids["Madrid"], club_ids[0], lowest_division),
    )
    ensure_user_avatar(conn, admin_id, "male")
    conn.execute(
        "INSERT INTO playtomic_connections (user_id, status) VALUES (?, 'not_connected')",
        (admin_id,),
    )

    players_by_division = {lowest_division: []}
    levels = ["Principiante", "Intermedio", "Avanzado"]
    for index, name in enumerate(PLAYERS):
        city, region, lat, lng = LOCATIONS[index % len(LOCATIONS)]
        user_cursor = conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'player')",
            (f"{slug(name)}@demo.playup", hash_password("demo123")),
        )
        user_id = user_cursor.lastrowid
        rating = 920 + index * 12
        conn.execute(
            """
            INSERT INTO player_profiles
            (user_id, display_name, gender, location_id, club_id, level_guess, lat, lng, current_division_id, rating, availability_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name,
                "male" if index % 2 == 0 else "female",
                location_ids[city],
                club_ids[index % len(club_ids)],
                levels[index % len(levels)],
                lat + ((index % 4) - 1.5) * 0.02,
                lng + ((index % 5) - 2) * 0.02,
                lowest_division,
                rating,
                "Tardes y fines de semana",
            ),
        )
        ensure_user_avatar(conn, user_id, "male" if index % 2 == 0 else "female")
        conn.execute(
            "INSERT INTO playtomic_connections (user_id, playtomic_id, status) VALUES (?, ?, ?)",
            (user_id, f"pt-{1000 + index}" if index % 5 == 0 else "", "pending" if index % 5 == 0 else "not_connected"),
        )
        players_by_division[lowest_division].append(
            {
                "user_id": user_id,
                "lat": lat,
                "lng": lng,
                "city": city,
                "region": region,
                "rating": rating,
            }
        )

    create_groups_for_season(conn, season_id, players_by_division)
    seed_monthly_challenges(conn, season_id)
    seed_activation_state(conn)
    conn.commit()
    seed_matches(conn, season_id)
    conn.commit()


def ensure_beta_profile_integrity(conn):
    rows = conn.execute(
        """
        SELECT p.user_id, p.gender, ab.type AS avatar_type
        FROM player_profiles p
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        ORDER BY p.user_id
        """
    ).fetchall()
    for index, row in enumerate(rows):
        gender = row["gender"] if row["gender"] in ("male", "female") else row["avatar_type"] if row["avatar_type"] in ("male", "female") else "male" if index % 2 == 0 else "female"
        conn.execute(
            """
            UPDATE player_profiles
            SET gender = ?,
                level_guess = CASE
                    WHEN level_guess IN ('Principiante', 'Intermedio', 'Avanzado') THEN level_guess
                    WHEN level_guess = 'Competicion' THEN 'Avanzado'
                    WHEN level_guess = 'Iniciacion' THEN 'Principiante'
                    ELSE 'Intermedio'
                END,
                availability_text = CASE WHEN COALESCE(availability_text, '') = '' THEN 'Tardes y fines de semana' ELSE availability_text END
            WHERE user_id = ?
            """,
            (gender, row["user_id"]),
        )
        if row["avatar_type"] == "neutral":
            base_id = conn.execute(
                "SELECT id FROM avatar_bases WHERE type = ? AND is_active = 1 ORDER BY id LIMIT 1",
                (gender,),
            ).fetchone()
            if base_id:
                conn.execute("UPDATE user_avatars SET base_avatar_id = ? WHERE user_id = ?", (base_id["id"], row["user_id"]))


def seed_activation_state(conn):
    season = conn.execute("SELECT id FROM seasons WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
    if not season:
        return
    active_count = scalar(conn, "SELECT COUNT(*) FROM player_profiles WHERE last_active_at IS NOT NULL")
    if not active_count:
        players = conn.execute(
            """
            SELECT gm.user_id, gm.group_id, gm.season_id
            FROM group_members gm
            JOIN users u ON u.id = gm.user_id
            WHERE gm.season_id = ? AND u.role = 'player'
            ORDER BY gm.user_id
            LIMIT 8
            """,
            (season["id"],),
        ).fetchall()
        for index, player in enumerate(players):
            conn.execute(
                """
                UPDATE player_profiles
                SET last_active_at = datetime('now', ?),
                    available_for_play = ?,
                    availability_updated_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE availability_updated_at END
                WHERE user_id = ?
                """,
                (f"-{index * 3} hours", 1 if index < 5 else 0, 1 if index < 5 else 0, player["user_id"]),
            )
        open_count = scalar(conn, "SELECT COUNT(*) FROM match_requests WHERE season_id = ? AND status = 'open'", (season["id"],))
        if not open_count:
            for player in players[:3]:
                conn.execute(
                    """
                    INSERT INTO match_requests (season_id, group_id, owner_id, status, message, expires_at)
                    VALUES (?, ?, ?, 'open', 'Busco partido competitivo hoy.', datetime('now', '+6 hours'))
                    """,
                    (player["season_id"], player["group_id"], player["user_id"]),
                )


def seed_matches(conn, season_id):
    groups = conn.execute("SELECT id FROM groups WHERE season_id = ?", (season_id,)).fetchall()
    scores = ["6-4 6-3", "7-5 4-6 10-8", "6-2 6-4", "4-6 6-3 10-7", "7-6 6-4"]
    for group in groups:
        members = [row["user_id"] for row in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group["id"],)).fetchall()]
        for match_number, index in enumerate(range(0, max(0, len(members) - 3), 4)):
            player_a = members[index]
            player_a_partner = members[index + 1]
            player_b = members[index + 2]
            player_b_partner = members[index + 3]
            score = scores[index % len(scores)]
            status = "confirmed" if match_number % 3 != 0 else "pending_confirmation"
            create_seed_match(conn, season_id, group["id"], player_a, player_a_partner, player_b, player_b_partner, score, status)
        if len(members) >= 4:
            create_seed_match(conn, season_id, group["id"], members[0], members[1], members[2], members[3], "6-4 3-6 10-8", "conflict")


def create_seed_match(conn, season_id, group_id, player_a, player_a_partner, player_b, player_b_partner, score, status):
    parsed = parse_score(score)
    winner_team = parsed["winner_side"]
    loser_team = "B" if winner_team == "A" else "A"
    winner_id = player_a if winner_team == "A" else player_b
    loser_id = player_b if winner_team == "A" else player_a
    cursor = conn.execute(
        """
        INSERT INTO matches
        (season_id, group_id, player_a_id, player_b_id,
         team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id,
         status, created_by, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'confirmed' THEN CURRENT_TIMESTAMP ELSE NULL END)
        """,
        (season_id, group_id, player_a, player_b, player_a, player_a_partner, player_b, player_b_partner, status, player_a, status),
    )
    match_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO match_results
        (match_id, score, winner_id, loser_id, winner_team, loser_team, sets_won_winner, sets_won_loser,
         games_won_winner, games_won_loser, submitted_by, confirmed_by, conflict_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            score,
            winner_id,
            loser_id,
            winner_team,
            loser_team,
            parsed[winner_team.lower()]["sets_won"],
            parsed[loser_team.lower()]["sets_won"],
            parsed[winner_team.lower()]["games_won"],
            parsed[loser_team.lower()]["games_won"],
            player_a,
            player_b if status == "confirmed" else None,
            "Marcador discrepante. Pendiente de admin." if status == "conflict" else "",
        ),
    )
    if status == "conflict":
        conn.execute(
            "INSERT INTO admin_reviews (match_id, reason) VALUES (?, ?)",
            (match_id, "Resultado marcado como discrepante por el rival."),
        )
    if status == "confirmed":
        apply_match_xp(conn, match_id)
        apply_rating_for_match(conn, match_id)
