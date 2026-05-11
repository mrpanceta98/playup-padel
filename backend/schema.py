SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'player',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        region TEXT NOT NULL,
        country TEXT NOT NULL DEFAULT 'ES',
        lat REAL NOT NULL,
        lng REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clubs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location_id INTEGER NOT NULL REFERENCES locations(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS league_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL,
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS divisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level_id INTEGER NOT NULL REFERENCES league_levels(id),
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        starts_on TEXT NOT NULL,
        ends_on TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        closed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        division_id INTEGER NOT NULL REFERENCES divisions(id),
        name TEXT NOT NULL,
        location_city TEXT,
        location_region TEXT,
        centroid_lat REAL,
        centroid_lng REAL,
        max_players INTEGER NOT NULL DEFAULT 30,
        status TEXT NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL REFERENCES groups(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(group_id, user_id, season_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS player_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        display_name TEXT NOT NULL,
        gender TEXT NOT NULL DEFAULT '',
        location_id INTEGER NOT NULL REFERENCES locations(id),
        club_id INTEGER REFERENCES clubs(id),
        level_guess TEXT NOT NULL DEFAULT 'Intermedio',
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        current_division_id INTEGER REFERENCES divisions(id),
        current_group_id INTEGER REFERENCES groups(id),
        rating INTEGER NOT NULL DEFAULT 1000,
        xp_total INTEGER NOT NULL DEFAULT 0,
        xp_monthly INTEGER NOT NULL DEFAULT 0,
        avatar_outfit TEXT NOT NULL DEFAULT 'Carbon',
        avatar_racket TEXT NOT NULL DEFAULT 'Control',
        avatar_frame TEXT NOT NULL DEFAULT 'Bronze',
        avatar_background TEXT NOT NULL DEFAULT 'Court',
        streak_months INTEGER NOT NULL DEFAULT 0,
        playtomic_id TEXT NOT NULL DEFAULT '',
        available_for_play INTEGER NOT NULL DEFAULT 0,
        availability_text TEXT NOT NULL DEFAULT '',
        availability_updated_at TEXT,
        last_active_at TEXT,
        onboarding_completed_at TEXT,
        initial_mission_claimed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        group_id INTEGER NOT NULL REFERENCES groups(id),
        player_a_id INTEGER NOT NULL REFERENCES users(id),
        player_b_id INTEGER NOT NULL REFERENCES users(id),
        team_a_player_1_id INTEGER REFERENCES users(id),
        team_a_player_2_id INTEGER REFERENCES users(id),
        team_b_player_1_id INTEGER REFERENCES users(id),
        team_b_player_2_id INTEGER REFERENCES users(id),
        source TEXT NOT NULL DEFAULT 'manual',
        status TEXT NOT NULL DEFAULT 'pending_confirmation',
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TEXT,
        counts_for_ranking INTEGER NOT NULL DEFAULT 1,
        is_walkover INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        group_id INTEGER REFERENCES groups(id),
        challenger_id INTEGER NOT NULL REFERENCES users(id),
        challenged_id INTEGER NOT NULL REFERENCES users(id),
        challenger_partner_id INTEGER REFERENCES users(id),
        challenged_partner_id INTEGER REFERENCES users(id),
        type TEXT NOT NULL DEFAULT 'open',
        status TEXT NOT NULL DEFAULT 'pending',
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        reward_xp INTEGER NOT NULL DEFAULT 75,
        ranking_bonus_points INTEGER NOT NULL DEFAULT 0,
        match_id INTEGER REFERENCES matches(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        responded_at TEXT,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL UNIQUE REFERENCES matches(id),
        score TEXT NOT NULL,
        winner_id INTEGER REFERENCES users(id),
        loser_id INTEGER REFERENCES users(id),
        winner_team TEXT,
        loser_team TEXT,
        sets_won_winner INTEGER NOT NULL DEFAULT 0,
        sets_won_loser INTEGER NOT NULL DEFAULT 0,
        games_won_winner INTEGER NOT NULL DEFAULT 0,
        games_won_loser INTEGER NOT NULL DEFAULT 0,
        submitted_by INTEGER NOT NULL REFERENCES users(id),
        confirmed_by INTEGER REFERENCES users(id),
        conflict_note TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ranking_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        group_id INTEGER NOT NULL REFERENCES groups(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        points INTEGER NOT NULL,
        played INTEGER NOT NULL,
        wins INTEGER NOT NULL,
        losses INTEGER NOT NULL,
        walkovers INTEGER NOT NULL,
        set_average INTEGER NOT NULL,
        game_average INTEGER NOT NULL,
        opponent_strength REAL NOT NULL,
        rank_position INTEGER NOT NULL,
        valid_match_ids_json TEXT NOT NULL,
        discarded_match_ids_json TEXT NOT NULL,
        computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(season_id, group_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promotion_relegation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        from_division_id INTEGER REFERENCES divisions(id),
        to_division_id INTEGER REFERENCES divisions(id),
        from_group_id INTEGER REFERENCES groups(id),
        to_group_id INTEGER REFERENCES groups(id),
        movement TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rating_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        match_id INTEGER NOT NULL REFERENCES matches(id),
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        rating_before INTEGER NOT NULL,
        rating_after INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, match_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS xp_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        season_id INTEGER REFERENCES seasons(id),
        match_id INTEGER REFERENCES matches(id),
        amount INTEGER NOT NULL,
        kind TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        achievement_id INTEGER NOT NULL REFERENCES achievements(id),
        season_id INTEGER REFERENCES seasons(id),
        earned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, achievement_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS avatar_bases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        image_path TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS avatar_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        slot TEXT NOT NULL,
        rarity TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'accessory',
        required_level INTEGER NOT NULL DEFAULT 1,
        required_xp INTEGER NOT NULL DEFAULT 0,
        image_path TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        unlock_achievement_id INTEGER REFERENCES achievements(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_avatars (
        user_id INTEGER PRIMARY KEY REFERENCES users(id),
        base_avatar_id INTEGER NOT NULL REFERENCES avatar_bases(id),
        equipped_face INTEGER REFERENCES avatar_items(id),
        equipped_hair INTEGER REFERENCES avatar_items(id),
        equipped_hair_color INTEGER REFERENCES avatar_items(id),
        equipped_beard INTEGER REFERENCES avatar_items(id),
        equipped_top INTEGER REFERENCES avatar_items(id),
        equipped_bottom INTEGER REFERENCES avatar_items(id),
        equipped_shoes INTEGER REFERENCES avatar_items(id),
        equipped_racket INTEGER REFERENCES avatar_items(id),
        equipped_headband INTEGER REFERENCES avatar_items(id),
        equipped_wristband INTEGER REFERENCES avatar_items(id),
        equipped_overgrip INTEGER REFERENCES avatar_items(id),
        equipped_frame INTEGER REFERENCES avatar_items(id),
        equipped_background INTEGER REFERENCES avatar_items(id),
        equipped_effect INTEGER REFERENCES avatar_items(id),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_avatar_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        avatar_item_id INTEGER NOT NULL REFERENCES avatar_items(id),
        earned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        unlocked_at TEXT,
        equipped INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, avatar_item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playtomic_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        playtomic_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'not_connected',
        connected_at TEXT,
        last_sync_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL REFERENCES matches(id),
        status TEXT NOT NULL DEFAULT 'open',
        reason TEXT NOT NULL,
        resolved_by INTEGER REFERENCES users(id),
        resolution TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        related_type TEXT,
        related_id INTEGER,
        priority INTEGER NOT NULL DEFAULT 1,
        event_key TEXT NOT NULL DEFAULT '',
        read_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS error_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        type TEXT NOT NULL,
        message TEXT NOT NULL,
        stack_trace TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        resolved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS beta_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        type TEXT NOT NULL DEFAULT 'feedback',
        rating INTEGER,
        message TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS monthly_challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        code TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        target INTEGER NOT NULL DEFAULT 1,
        reward_xp INTEGER NOT NULL DEFAULT 0,
        reward_avatar_item_id INTEGER REFERENCES avatar_items(id),
        reward_achievement_code TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(season_id, code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_monthly_challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        monthly_challenge_id INTEGER NOT NULL REFERENCES monthly_challenges(id),
        status TEXT NOT NULL DEFAULT 'pending',
        claimed_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, monthly_challenge_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        group_id INTEGER NOT NULL REFERENCES groups(id),
        owner_id INTEGER NOT NULL REFERENCES users(id),
        joined_by_id INTEGER REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'open',
        message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_name TEXT NOT NULL,
        club_name TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL REFERENCES users(id),
        linked_user_id INTEGER REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        linked_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS free_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        partner_external_player_id INTEGER NOT NULL REFERENCES external_players(id),
        rival_1_external_player_id INTEGER NOT NULL REFERENCES external_players(id),
        rival_2_external_player_id INTEGER NOT NULL REFERENCES external_players(id),
        club_name TEXT NOT NULL DEFAULT '',
        played_on TEXT NOT NULL,
        score TEXT NOT NULL,
        winner_team TEXT NOT NULL,
        sets_won_user_team INTEGER NOT NULL DEFAULT 0,
        sets_won_rival_team INTEGER NOT NULL DEFAULT 0,
        games_won_user_team INTEGER NOT NULL DEFAULT 0,
        games_won_rival_team INTEGER NOT NULL DEFAULT 0,
        official_match_id INTEGER REFERENCES matches(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS free_match_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        free_match_id INTEGER NOT NULL REFERENCES free_matches(id),
        external_player_id INTEGER NOT NULL REFERENCES external_players(id),
        invited_by INTEGER NOT NULL REFERENCES users(id),
        token TEXT NOT NULL UNIQUE,
        registered_user_id INTEGER REFERENCES users(id),
        accepted_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(free_match_id, external_player_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        kind TEXT NOT NULL DEFAULT 'join_league',
        ref TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, kind)
    )
    """,
]


def init_schema(conn):
    for statement in SCHEMA:
        conn.execute(statement)
    ensure_match_pair_columns(conn)
    conn.commit()


def ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_match_pair_columns(conn):
    ensure_column(conn, "player_profiles", "gender", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "player_profiles", "available_for_play", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "player_profiles", "availability_text", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "player_profiles", "availability_updated_at", "TEXT")
    ensure_column(conn, "player_profiles", "last_active_at", "TEXT")
    ensure_column(conn, "player_profiles", "onboarding_completed_at", "TEXT")
    ensure_column(conn, "player_profiles", "initial_mission_claimed_at", "TEXT")
    ensure_column(conn, "matches", "team_a_player_1_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "matches", "team_a_player_2_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "matches", "team_b_player_1_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "matches", "team_b_player_2_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "match_results", "winner_team", "TEXT")
    ensure_column(conn, "match_results", "loser_team", "TEXT")
    ensure_column(conn, "challenges", "challenger_partner_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "challenges", "challenged_partner_id", "INTEGER REFERENCES users(id)")
    ensure_column(conn, "avatar_items", "category", "TEXT NOT NULL DEFAULT 'accessory'")
    ensure_column(conn, "avatar_items", "required_level", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "avatar_items", "required_xp", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "avatar_items", "image_path", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "avatar_items", "is_active", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "user_avatars", "equipped_headband", "INTEGER REFERENCES avatar_items(id)")
    ensure_column(conn, "user_avatars", "equipped_overgrip", "INTEGER REFERENCES avatar_items(id)")
    ensure_column(conn, "user_avatar_items", "unlocked_at", "TEXT")
    ensure_column(conn, "notifications", "priority", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "notifications", "event_key", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "free_matches", "official_match_id", "INTEGER REFERENCES matches(id)")
