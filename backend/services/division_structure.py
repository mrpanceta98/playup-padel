DIVISION_HIERARCHY = [
    ("local", "Local", "3a Local"),
    ("local", "Local", "2a Local"),
    ("local", "Local", "1a Local"),
    ("regional", "Regional", "5a Regional"),
    ("regional", "Regional", "4a Regional"),
    ("regional", "Regional", "3a Regional"),
    ("regional", "Regional", "2a Regional"),
    ("regional", "Regional", "1a Regional"),
    ("national", "Nacional", "7a Nacional"),
    ("national", "Nacional", "6a Nacional"),
    ("national", "Nacional", "5a Nacional"),
    ("national", "Nacional", "4a Nacional"),
    ("national", "Nacional", "3a Nacional"),
    ("national", "Nacional", "2a Nacional"),
    ("national", "Nacional", "1a Nacional"),
]

LOWEST_DIVISION_NAME = "3a Local"


def ensure_division_structure(conn):
    conn.execute("UPDATE league_levels SET sort_order = -id")
    conn.execute("UPDATE divisions SET sort_order = -id")
    level_ids = {}
    for sort_order, (scope, level_name, division_name) in enumerate(DIVISION_HIERARCHY, start=1):
        if scope not in level_ids:
            row = conn.execute("SELECT id FROM league_levels WHERE scope = ?", (scope,)).fetchone()
            if row:
                level_ids[scope] = row["id"]
                conn.execute(
                    "UPDATE league_levels SET name = ?, sort_order = ? WHERE id = ?",
                    (level_name, sort_order, row["id"]),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO league_levels (scope, name, sort_order) VALUES (?, ?, ?)",
                    (scope, level_name, sort_order),
                )
                level_ids[scope] = cursor.lastrowid
        row = conn.execute("SELECT id FROM divisions WHERE name = ?", (division_name,)).fetchone()
        if row:
            conn.execute(
                "UPDATE divisions SET level_id = ?, sort_order = ? WHERE id = ?",
                (level_ids[scope], sort_order, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO divisions (level_id, name, sort_order) VALUES (?, ?, ?)",
                (level_ids[scope], division_name, sort_order),
            )


def lowest_division_id(conn):
    row = conn.execute("SELECT id FROM divisions WHERE name = ?", (LOWEST_DIVISION_NAME,)).fetchone()
    return row["id"] if row else None


def migrate_initial_regional_starters_to_lowest(conn):
    lowest_id = lowest_division_id(conn)
    old_id_row = conn.execute("SELECT id FROM divisions WHERE name = '3a Regional'").fetchone()
    if not lowest_id or not old_id_row:
        return
    old_id = old_id_row["id"]
    has_history = conn.execute("SELECT COUNT(*) FROM promotion_relegation_history").fetchone()[0]
    active_season = conn.execute("SELECT id FROM seasons WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
    if has_history or not active_season:
        return
    conn.execute(
        "UPDATE player_profiles SET current_division_id = ? WHERE current_division_id = ?",
        (lowest_id, old_id),
    )
    affected_groups = conn.execute(
        "SELECT id FROM groups WHERE season_id = ? AND division_id = ?",
        (active_season["id"], old_id),
    ).fetchall()
    if not affected_groups:
        return
    conn.execute(
        "UPDATE groups SET division_id = ?, name = REPLACE(name, '3a Regional', '3a Local') WHERE season_id = ? AND division_id = ?",
        (lowest_id, active_season["id"], old_id),
    )
    conn.execute(
        """
        UPDATE player_profiles
        SET current_division_id = ?
        WHERE current_group_id IN (
            SELECT id FROM groups WHERE season_id = ? AND division_id = ?
        )
        """,
        (lowest_id, active_season["id"], lowest_id),
    )
