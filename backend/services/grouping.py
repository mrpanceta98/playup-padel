import math
import string


MIN_GROUP_SIZE = 20
OPTIMAL_GROUP_MIN = 25
MAX_GROUP_SIZE = 30


def distance_km(a_lat, a_lng, b_lat, b_lng):
    earth = 6371
    d_lat = math.radians(b_lat - a_lat)
    d_lng = math.radians(b_lng - a_lng)
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    hav = math.sin(d_lat / 2) ** 2 + math.sin(d_lng / 2) ** 2 * math.cos(lat1) * math.cos(lat2)
    return earth * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav))


def target_group_count(player_count):
    if player_count <= 0:
        return 0
    return max(1, math.ceil(player_count / MAX_GROUP_SIZE))


def balanced_group_sizes(player_count):
    groups_count = target_group_count(player_count)
    if groups_count == 0:
        return []
    base = player_count // groups_count
    remainder = player_count % groups_count
    return [base + (1 if index < remainder else 0) for index in range(groups_count)]


def group_letter(index):
    letters = string.ascii_uppercase
    if index < len(letters):
        return letters[index]
    return letters[(index // len(letters)) - 1] + letters[index % len(letters)]


def create_groups_for_season(conn, season_id, players_by_division):
    created = {}
    for division_id, players in players_by_division.items():
        created[division_id] = recreate_division_groups(conn, season_id, division_id, players)
    return created


def recreate_division_groups(conn, season_id, division_id, players):
    players = [dict(player) for player in players]
    conn.execute(
        """
        UPDATE player_profiles
        SET current_group_id = NULL
        WHERE current_group_id IN (SELECT id FROM groups WHERE season_id = ? AND division_id = ?)
        """,
        (season_id, division_id),
    )
    conn.execute(
        """
        DELETE FROM ranking_entries
        WHERE season_id = ?
          AND group_id IN (SELECT id FROM groups WHERE season_id = ? AND division_id = ?)
        """,
        (season_id, season_id, division_id),
    )
    conn.execute(
        """
        DELETE FROM group_members
        WHERE season_id = ?
          AND group_id IN (SELECT id FROM groups WHERE season_id = ? AND division_id = ?)
        """,
        (season_id, season_id, division_id),
    )
    conn.execute("DELETE FROM groups WHERE season_id = ? AND division_id = ?", (season_id, division_id))
    chunks = build_balanced_chunks(players)
    group_ids = []
    division = conn.execute("SELECT name FROM divisions WHERE id = ?", (division_id,)).fetchone()
    for index, chunk in enumerate(chunks):
        if not chunk:
            continue
        avg_lat = sum(player["lat"] for player in chunk) / len(chunk)
        avg_lng = sum(player["lng"] for player in chunk) / len(chunk)
        region = most_common(chunk, "region")
        city = most_common(chunk, "city")
        cursor = conn.execute(
            """
            INSERT INTO groups
            (season_id, division_id, name, location_city, location_region, centroid_lat, centroid_lng, max_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (season_id, division_id, f"{division['name']} Grupo {group_letter(index)}", city, region, avg_lat, avg_lng, MAX_GROUP_SIZE),
        )
        group_id = cursor.lastrowid
        group_ids.append(group_id)
        for player in chunk:
            conn.execute(
                "INSERT INTO group_members (group_id, user_id, season_id) VALUES (?, ?, ?)",
                (group_id, player["user_id"], season_id),
            )
            conn.execute(
                "UPDATE player_profiles SET current_group_id = ?, current_division_id = ? WHERE user_id = ?",
                (group_id, division_id, player["user_id"]),
            )
    return group_ids


def build_balanced_chunks(players):
    if not players:
        return []
    sizes = balanced_group_sizes(len(players))
    if len(sizes) == 1:
        return [sorted(players, key=geo_rating_key)]
    ordered = stable_or_geo_rating_order(players, len(sizes))
    chunks = []
    offset = 0
    for size in sizes:
        chunks.append(ordered[offset : offset + size])
        offset += size
    return chunks


def stable_or_geo_rating_order(players, groups_count):
    previous_groups = {}
    for player in players:
        previous_group = player.get("previous_group_id") or player.get("current_group_id")
        if previous_group:
            previous_groups.setdefault(previous_group, []).append(player)
    if len(previous_groups) == groups_count:
        buckets = [sorted(bucket, key=geo_rating_key) for _, bucket in sorted(previous_groups.items())]
        sizes = [len(bucket) for bucket in buckets]
        if max(sizes) <= MAX_GROUP_SIZE and (min(sizes) >= MIN_GROUP_SIZE or len(players) < MIN_GROUP_SIZE):
            return [player for bucket in buckets for player in bucket]
    return sorted(players, key=geo_rating_key)


def geo_rating_key(player):
    return (
        player.get("region") or "",
        player.get("city") or "",
        geographic_band(player),
        -int(player.get("rating") or 0),
        player.get("user_id") or 0,
    )


def geographic_band(player):
    lat = float(player.get("lat") or 0)
    lng = float(player.get("lng") or 0)
    return (round(lat / 0.05), round(lng / 0.05))


def most_common(players, field):
    counts = {}
    for player in players:
        value = player.get(field) or ""
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if counts else ""


def division_players(conn, season_id, division_id):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.user_id, p.lat, p.lng, p.rating, l.city, l.region, p.current_group_id AS previous_group_id
            FROM player_profiles p
            JOIN users u ON u.id = p.user_id
            JOIN locations l ON l.id = p.location_id
            WHERE u.role = 'player'
              AND p.current_division_id = ?
              AND (
                p.current_group_id IS NULL
                OR p.current_group_id IN (SELECT id FROM groups WHERE season_id = ?)
              )
            ORDER BY p.user_id
            """,
            (division_id, season_id),
        ).fetchall()
    ]


def division_has_group_activity(conn, season_id, division_id):
    group_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM groups WHERE season_id = ? AND division_id = ?",
            (season_id, division_id),
        ).fetchall()
    ]
    if not group_ids:
        return False
    placeholders = ",".join("?" for _ in group_ids)
    for table in ("matches", "challenges", "match_requests"):
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE season_id = ? AND group_id IN ({placeholders}) LIMIT 1",
            (season_id, *group_ids),
        ).fetchone():
            return True
    return False


def rebalance_division_if_safe(conn, season_id, division_id):
    players = division_players(conn, season_id, division_id)
    if not players:
        return []
    expected = target_group_count(len(players))
    groups = conn.execute(
        """
        SELECT g.id, COUNT(gm.id) AS players
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.active = 1
        WHERE g.season_id = ? AND g.division_id = ?
        GROUP BY g.id
        ORDER BY g.id
        """,
        (season_id, division_id),
    ).fetchall()
    sizes = [row["players"] for row in groups]
    needs_rebalance = len(groups) != expected or any(size > MAX_GROUP_SIZE for size in sizes) or (sizes and max(sizes) - min(sizes) > 1)
    if not needs_rebalance:
        return [row["id"] for row in groups]
    if division_has_group_activity(conn, season_id, division_id):
        return [row["id"] for row in groups]
    return recreate_division_groups(conn, season_id, division_id, players)


def assign_new_player_to_group(conn, user_id, division_id, season_id):
    profile = conn.execute(
        """
        SELECT p.user_id, p.lat, p.lng, l.city, l.region, p.rating
        FROM player_profiles p
        JOIN locations l ON l.id = p.location_id
        WHERE p.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    groups = conn.execute(
        """
        SELECT g.*, COUNT(gm.id) AS member_count
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.active = 1
        WHERE g.season_id = ? AND g.division_id = ?
        GROUP BY g.id
        HAVING member_count < g.max_players
        """,
        (season_id, division_id),
    ).fetchall()
    if groups:
        group = sorted(
            groups,
            key=lambda g: (
                same_city_penalty(profile, g),
                distance_km(profile["lat"], profile["lng"], g["centroid_lat"], g["centroid_lng"]),
                g["member_count"],
            ),
        )[0]
        group_id = group["id"]
    else:
        group_id = create_single_player_group(conn, season_id, division_id, profile)

    conn.execute(
        "INSERT OR IGNORE INTO group_members (group_id, user_id, season_id) VALUES (?, ?, ?)",
        (group_id, user_id, season_id),
    )
    conn.execute(
        "UPDATE player_profiles SET current_group_id = ?, current_division_id = ? WHERE user_id = ?",
        (group_id, division_id, user_id),
    )
    group_ids = rebalance_division_if_safe(conn, season_id, division_id)
    if group_ids:
        current = conn.execute("SELECT current_group_id FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
        return current["current_group_id"]
    return group_id


def same_city_penalty(profile, group):
    if profile["city"] == group["location_city"]:
        return 0
    if profile["region"] == group["location_region"]:
        return 1
    return 2


def create_single_player_group(conn, season_id, division_id, profile):
    division = conn.execute("SELECT name FROM divisions WHERE id = ?", (division_id,)).fetchone()
    group_number = conn.execute(
        "SELECT COUNT(*) FROM groups WHERE season_id = ? AND division_id = ?",
        (season_id, division_id),
    ).fetchone()[0]
    cursor = conn.execute(
        """
        INSERT INTO groups
        (season_id, division_id, name, location_city, location_region, centroid_lat, centroid_lng, max_players)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            season_id,
            division_id,
            f"{division['name']} Grupo {group_letter(group_number)}",
            profile["city"],
            profile["region"],
            profile["lat"],
            profile["lng"],
            MAX_GROUP_SIZE,
        ),
    )
    return cursor.lastrowid
