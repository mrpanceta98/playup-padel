from backend.database import scalar
from backend.services.match_teams import team_ids, team_rating_average, winner_team
from backend.services.notifications import create_notification


XP_PLAY_VALID = 50
XP_WIN = 100
XP_LOSS = 40
XP_PROMOTION = 250
XP_TOP_3 = 150
XP_TEN_MATCHES = 200


ACHIEVEMENTS = [
    ("debut", "Debut PlayUp Padel", "Primer partido registrado."),
    ("top_3", "Top 3", "Termina el mes entre los tres primeros."),
    ("promotion", "Ascenso", "Asciende de division."),
    ("undefeated", "Invicto", "Termina el mes sin derrotas con minimo 5 partidos."),
    ("iron_player", "Iron Player", "Completa 10 partidos en un mes."),
    ("giant_killer", "Giant Killer", "Gana a un rival con rating superior."),
    ("regular", "Regular", "Juega al menos un partido durante 3 meses seguidos."),
    ("local_legend", "Leyenda Local", "Alcanza 1a Local."),
    ("national_path", "Camino Nacional", "Alcanza una division nacional."),
    ("challenge_accepted", "Reto aceptado", "Acepta tu primer reto PlayUp Padel."),
    ("challenge_completed", "Reto completado", "Completa un partido nacido de un reto."),
    ("weekly_challenger", "Semana activa", "Completa un reto semanal."),
    ("profile_complete", "Perfil listo", "Completa la configuracion inicial de PlayUp Padel."),
    ("monthly_regular", "Mes constante", "Completa un reto mensual de actividad."),
    ("monthly_winner", "Mes ganador", "Completa un reto mensual de victorias."),
    ("monthly_podium", "Candidato al ascenso", "Entra en zona de ascenso durante la temporada."),
    ("monthly_clean_sheet", "Resultados al dia", "Confirma todos tus resultados pendientes del mes."),
    ("consecutive_promotion", "Ascenso consecutivo", "Asciende durante dos temporadas consecutivas."),
    ("repeat_top_3", "Top 3 repetido", "Termina varias temporadas en puestos de ascenso."),
]

AVATAR_BASES = [
    ("base_male", "Avatar masculino base", "male", "/assets/avatars/male_base.png"),
    ("base_female", "Avatar femenino base", "female", "/assets/avatars/female_base.png"),
    ("base_neutral", "Avatar neutro base", "neutral", "/assets/avatars/neutral_base.png"),
]

AVATAR_CATEGORIES = {
    "face": "equipped_face",
    "hair": "equipped_hair",
    "hair_color": "equipped_hair_color",
    "beard": "equipped_beard",
    "top": "equipped_top",
    "bottom": "equipped_bottom",
    "shoes": "equipped_shoes",
    "racket": "equipped_racket",
    "headband": "equipped_headband",
    "wristband": "equipped_wristband",
    "overgrip": "equipped_overgrip",
    "frame": "equipped_frame",
    "background": "equipped_background",
    "effect": "equipped_effect",
}

RARITY_ORDER = {
    "comun": 1,
    "poco_comun": 2,
    "raro": 3,
    "epico": 4,
    "legendario": 5,
}


def xp_required_for_level(level):
    return max(0, (level - 1) * 500)


AVATAR_ITEMS = [
    ("face_focused", "Cara concentrada", "face", "comun", 1, 0, "/assets/avatar/item-accessory.svg"),
    ("face_competitive", "Cara competitiva", "face", "poco_comun", 10, xp_required_for_level(10), "/assets/avatar/item-accessory.svg"),
    ("face_ice", "Cara temple final", "face", "raro", 18, xp_required_for_level(18), "/assets/avatar/item-accessory.svg"),
    ("top_graphite", "Camiseta Graphite", "top", "comun", 1, 0, "/assets/avatar-items/top_male_01.png"),
    ("top_beta_white", "Camiseta Beta White", "top", "comun", 1, 0, "/assets/avatar-items/top_male_02.png"),
    ("top_beta_lime", "Camiseta Beta Lime", "top", "comun", 1, 0, "/assets/avatar-items/top_male_03.png"),
    ("top_white", "Camiseta White Court", "top", "comun", 6, xp_required_for_level(6), "/assets/avatar-items/top_male_02.png"),
    ("top_lime", "Camiseta Lime", "top", "comun", 6, xp_required_for_level(6), "/assets/avatar-items/top_male_03.png"),
    ("top_navy", "Camiseta Navy Pro", "top", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/top_male_04.png"),
    ("top_legend", "Equipacion Legendaria", "top", "legendario", 30, xp_required_for_level(30), "/assets/avatar-items/top_male_05.png"),
    ("top_female_black", "Top Black Court", "top", "comun", 1, 0, "/assets/avatar-items/top_female_01.png"),
    ("top_female_white_beta", "Top Beta White", "top", "comun", 1, 0, "/assets/avatar-items/top_female_02.png"),
    ("top_female_blue_beta", "Top Beta Blue", "top", "comun", 1, 0, "/assets/avatar-items/top_female_05.png"),
    ("top_female_lime", "Top Lime Pro", "top", "comun", 6, xp_required_for_level(6), "/assets/avatar-items/top_female_03.png"),
    ("bottom_carbon", "Short Carbon", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_male_01.png"),
    ("bottom_beta_white", "Short Beta White", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_male_02.png"),
    ("bottom_beta_navy", "Short Beta Navy", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_male_04.png"),
    ("bottom_white", "Short White Court", "bottom", "comun", 7, xp_required_for_level(7), "/assets/avatar-items/bottom_male_02.png"),
    ("bottom_navy", "Short Navy", "bottom", "poco_comun", 7, xp_required_for_level(7), "/assets/avatar-items/bottom_male_04.png"),
    ("bottom_pro", "Falda/Short Pro League", "bottom", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/bottom_female_03.png"),
    ("bottom_female_black", "Falda Black Court", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_female_01.png"),
    ("bottom_female_white", "Falda White Court", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_female_02.png"),
    ("bottom_female_lime", "Falda Lime Court", "bottom", "comun", 1, 0, "/assets/avatar-items/bottom_female_03.png"),
    ("bottom_elite", "Falda/Short Elite", "bottom", "legendario", 30, xp_required_for_level(30), "/assets/avatar-items/bottom_female_06.png"),
    ("racket_control", "Pala Control", "racket", "comun", 1, 0, "/assets/avatar-items/racket_01.png"),
    ("racket_blue_beta", "Pala Beta Blue", "racket", "comun", 1, 0, "/assets/avatar-items/racket_05.png"),
    ("racket_gold_beta", "Pala Beta Gold", "racket", "comun", 1, 0, "/assets/avatar-items/racket_03.png"),
    ("racket_power", "Pala Power", "racket", "comun", 5, xp_required_for_level(5), "/assets/avatar-items/racket_02.png"),
    ("racket_hybrid", "Pala Hybrid", "racket", "poco_comun", 10, xp_required_for_level(10), "/assets/avatar-items/racket_03.png"),
    ("racket_tour", "Pala Tour Carbon", "racket", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/racket_05.png"),
    ("racket_legend", "Pala Epica", "racket", "epico", 25, xp_required_for_level(25), "/assets/avatar-items/racket_female_06.png"),
    ("shoes_white", "Zapatillas White", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_02.png"),
    ("shoes_black_beta", "Zapatillas Beta Black", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_01.png"),
    ("shoes_blue_beta", "Zapatillas Beta Blue", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_04.png"),
    ("shoes_female_white_beta", "Zapatillas Beta White", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_female_01.png"),
    ("shoes_female_mint_beta", "Zapatillas Beta Mint", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_female_04.png"),
    ("shoes_female_pink_beta", "Zapatillas Beta Pink", "shoes", "comun", 1, 0, "/assets/avatar-items/shoes_female_05.png"),
    ("shoes_lime", "Zapatillas Lime", "shoes", "comun", 12, xp_required_for_level(12), "/assets/avatar-items/shoes_01.png"),
    ("shoes_grip", "Zapatillas Grip+", "shoes", "poco_comun", 12, xp_required_for_level(12), "/assets/avatar-items/shoes_03.png"),
    ("shoes_speed", "Zapatillas Speed", "shoes", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/shoes_female_04.png"),
    ("shoes_elite", "Zapatillas Elite", "shoes", "epico", 25, xp_required_for_level(25), "/assets/avatar-items/shoes_female_06.png"),
    ("frame_bronze", "Marco Bronce", "frame", "comun", 1, 0, "/assets/avatar/item-frame.svg"),
    ("frame_silver", "Marco Plata", "frame", "comun", 10, xp_required_for_level(10), "/assets/avatar/item-frame.svg"),
    ("frame_gold", "Marco Oro", "frame", "raro", 20, xp_required_for_level(20), "/assets/avatar/item-frame.svg"),
    ("frame_podium", "Marco Epico", "frame", "epico", 25, xp_required_for_level(25), "/assets/avatar/item-frame.svg"),
    ("frame_legend", "Marco de Ascenso", "frame", "legendario", 99, 999999, "/assets/avatar/item-frame.svg", "promotion"),
    ("background_court", "Fondo Pista", "background", "comun", 1, 0, "/assets/avatar/item-background.svg"),
    ("background_night", "Fondo Night Court", "background", "comun", 20, xp_required_for_level(20), "/assets/avatar/item-background.svg"),
    ("background_regional", "Fondo Regional", "background", "poco_comun", 20, xp_required_for_level(20), "/assets/avatar/item-background.svg"),
    ("background_arena", "Fondo Arena Final", "background", "epico", 25, xp_required_for_level(25), "/assets/avatar/item-background.svg"),
    ("background_legend", "Fondo Leyenda", "background", "legendario", 30, xp_required_for_level(30), "/assets/avatar/item-background.svg"),
    ("hair_short", "Peinado corto", "hair", "comun", 1, 0, "/assets/avatar-items/hair_male_01.png"),
    ("hair_male_side", "Peinado Side Court", "hair", "comun", 1, 0, "/assets/avatar-items/hair_male_02.png"),
    ("hair_male_curl", "Peinado Curl Court", "hair", "comun", 1, 0, "/assets/avatar-items/hair_male_03.png"),
    ("hair_male_sweep", "Peinado Sweep Pro", "hair", "comun", 1, 0, "/assets/avatar-items/hair_male_04.png"),
    ("hair_male_waves", "Peinado Waves Pro", "hair", "comun", 1, 0, "/assets/avatar-items/hair_male_05.png"),
    ("hair_tied", "Peinado recogido", "hair", "comun", 1, 0, "/assets/avatar-items/hair_female_01.png"),
    ("hair_female_bun", "Peinado Bun Court", "hair", "comun", 1, 0, "/assets/avatar-items/hair_female_02.png"),
    ("hair_female_pony", "Peinado Pony Pro", "hair", "comun", 1, 0, "/assets/avatar-items/hair_female_03.png"),
    ("hair_female_braid", "Peinado Braid Pro", "hair", "comun", 1, 0, "/assets/avatar-items/hair_female_04.png"),
    ("hair_fade", "Fade competitivo", "hair", "poco_comun", 3, xp_required_for_level(3), "/assets/avatar-items/hair_male_03.png"),
    ("hair_waves", "Ondas Pro", "hair", "raro", 10, xp_required_for_level(10), "/assets/avatar-items/hair_female_05.png"),
    ("hair_color_dark", "Pelo oscuro", "hair_color", "comun", 1, 0, "/assets/avatar-items/hair_male_02.png"),
    ("hair_color_brown_beta", "Pelo castaño", "hair_color", "comun", 1, 0, "/assets/avatar-items/hair_male_04.png"),
    ("hair_color_light_beta", "Pelo claro beta", "hair_color", "comun", 1, 0, "/assets/avatar-items/hair_female_02.png"),
    ("hair_color_light", "Pelo claro", "hair_color", "poco_comun", 6, xp_required_for_level(6), "/assets/avatar-items/hair_female_02.png"),
    ("beard_clean", "Sin barba", "beard", "comun", 3, xp_required_for_level(3), "/assets/avatar-items/beard_01.png"),
    ("beard_short", "Barba corta", "beard", "comun", 3, xp_required_for_level(3), "/assets/avatar-items/beard_02.png"),
    ("beard_full", "Barba completa", "beard", "poco_comun", 8, xp_required_for_level(8), "/assets/avatar-items/beard_05.png"),
    ("headband_black", "Diadema Black", "headband", "comun", 4, xp_required_for_level(4), "/assets/avatar-items/headband_01.png"),
    ("headband_white", "Diadema White", "headband", "comun", 4, xp_required_for_level(4), "/assets/avatar-items/headband_02.png"),
    ("headband_lime", "Diadema Lime", "headband", "poco_comun", 8, xp_required_for_level(8), "/assets/avatar-items/headband_04.png"),
    ("headband_female_pro", "Diadema Pro", "headband", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/headband_female_03.png"),
    ("wristband_black", "Muñequera Black", "wristband", "comun", 2, xp_required_for_level(2), "/assets/avatar-items/wristband_01.png"),
    ("wristband_white", "Muñequera White", "wristband", "comun", 2, xp_required_for_level(2), "/assets/avatar-items/wristband_02.png"),
    ("wristband_lime", "Muñequera Lime", "wristband", "poco_comun", 5, xp_required_for_level(5), "/assets/avatar-items/wristband_03.png"),
    ("wristband_elite", "Muñequera Elite", "wristband", "raro", 15, xp_required_for_level(15), "/assets/avatar-items/wristband_female_04.png"),
    ("overgrip_black", "Overgrip Black", "overgrip", "comun", 8, xp_required_for_level(8), "/assets/avatar-items/overgrip_01.png"),
    ("overgrip_white", "Overgrip White", "overgrip", "comun", 8, xp_required_for_level(8), "/assets/avatar-items/overgrip_02.png"),
    ("overgrip_lime", "Overgrip Lime", "overgrip", "poco_comun", 8, xp_required_for_level(8), "/assets/avatar-items/overgrip_03.png"),
    ("overgrip_blue", "Overgrip Blue", "overgrip", "raro", 12, xp_required_for_level(12), "/assets/avatar-items/overgrip_04.png"),
    ("overgrip_purple", "Overgrip Giant Killer", "overgrip", "epico", 99, 999999, "/assets/avatar-items/overgrip_06.png", "giant_killer"),
    ("effect_level_aura", "Aura de nivel", "effect", "comun", 18, xp_required_for_level(18), "/assets/avatar/item-effect.svg"),
    ("effect_promotion", "Efecto Legendario", "effect", "legendario", 30, xp_required_for_level(30), "/assets/avatar/item-effect.svg"),
    ("season_frame_may", "Marco Temporada Mayo", "frame", "epico", 99, 999999, "/assets/avatar/item-frame.svg", "top_3"),
    ("season_background_may", "Fondo Temporada Mayo", "background", "epico", 99, 999999, "/assets/avatar/item-background.svg", "iron_player"),
    ("season_effect_may", "Efecto Temporada Mayo", "effect", "legendario", 99, 999999, "/assets/avatar/item-effect.svg", "monthly_winner"),
]


def seed_achievements(conn):
    for code, name, description in ACHIEVEMENTS:
        conn.execute(
            "INSERT OR IGNORE INTO achievements (code, name, description) VALUES (?, ?, ?)",
            (code, name, description),
        )
    seed_avatar_catalog(conn)


def seed_avatar_catalog(conn):
    for code, name, avatar_type, image_path in AVATAR_BASES:
        conn.execute(
            """
            INSERT INTO avatar_bases (code, name, type, image_path, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                image_path = excluded.image_path,
                is_active = 1
            """,
            (code, name, avatar_type, image_path),
        )
    for item in AVATAR_ITEMS:
        code, name, category, rarity, required_level, required_xp, image_path = item[:7]
        achievement_code = item[7] if len(item) > 7 else None
        unlock_achievement_id = scalar(conn, "SELECT id FROM achievements WHERE code = ?", (achievement_code,)) if achievement_code else None
        conn.execute(
            """
            INSERT INTO avatar_items
            (code, name, slot, category, rarity, required_level, required_xp, image_path, is_active, unlock_achievement_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                slot = excluded.slot,
                category = excluded.category,
                rarity = excluded.rarity,
                required_level = excluded.required_level,
                required_xp = excluded.required_xp,
                image_path = excluded.image_path,
                is_active = 1,
                unlock_achievement_id = excluded.unlock_achievement_id
            """,
            (code, name, category, category, rarity, required_level, required_xp, image_path, unlock_achievement_id),
        )


def xp_level(xp_total):
    return max(1, xp_total // 500 + 1)


def notify_avatar_unlocks(conn, user_id, item_ids):
    if not item_ids:
        return
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"SELECT id, name FROM avatar_items WHERE id IN ({placeholders}) ORDER BY required_level, required_xp, id",
        item_ids,
    ).fetchall()
    for row in rows:
        create_notification(
            conn,
            user_id,
            "reward",
            "Has desbloqueado un nuevo item",
            f"{row['name']} ya esta disponible en tu avatar.",
            "avatar_item",
            row["id"],
            priority=2,
            event_key=f"reward:avatar_item:{row['id']}",
        )


def sync_avatar_locks(conn, user_id, level, total_xp):
    rows = conn.execute(
        """
        SELECT ai.id, ai.category
        FROM avatar_items ai
        JOIN user_avatar_items uai ON uai.avatar_item_id = ai.id AND uai.user_id = ?
        WHERE ai.unlock_achievement_id IS NULL
          AND (ai.required_level > ? OR ai.required_xp > ?)
        """,
        (user_id, level, total_xp),
    ).fetchall()
    locked_ids = [row["id"] for row in rows]
    if not locked_ids:
        return
    for row in rows:
        field = AVATAR_CATEGORIES.get(row["category"])
        if field:
            conn.execute(
                f"UPDATE user_avatars SET {field} = NULL, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND {field} = ?",
                (user_id, row["id"]),
            )
    placeholders = ",".join("?" for _ in locked_ids)
    conn.execute(
        f"DELETE FROM user_avatar_items WHERE user_id = ? AND avatar_item_id IN ({placeholders})",
        (user_id, *locked_ids),
    )


def base_avatar_id(conn, avatar_type="neutral"):
    if avatar_type not in ("male", "female", "neutral"):
        avatar_type = "neutral"
    row = conn.execute(
        "SELECT id FROM avatar_bases WHERE type = ? AND is_active = 1 ORDER BY id LIMIT 1",
        (avatar_type,),
    ).fetchone()
    if not row and avatar_type == "neutral":
        row = conn.execute("SELECT id FROM avatar_bases WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
    if not row:
        seed_avatar_catalog(conn)
        row = conn.execute(
            "SELECT id FROM avatar_bases WHERE type = ? AND is_active = 1 ORDER BY id LIMIT 1",
            (avatar_type,),
        ).fetchone()
    return row["id"] if row else None


def ensure_user_avatar(conn, user_id, avatar_type="neutral"):
    existing = conn.execute("SELECT * FROM user_avatars WHERE user_id = ?", (user_id,)).fetchone()
    resolved_avatar_type = avatar_type if avatar_type in ("male", "female") else avatar_type_for_user(conn, user_id, existing)
    if existing:
        unlock_avatar_items_for_user(conn, user_id)
        if not avatar_combo_complete(existing):
            equip_initial_avatar_combo(conn, user_id, resolved_avatar_type)
        return existing
    base_id = base_avatar_id(conn, resolved_avatar_type)
    if not base_id:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO user_avatars (user_id, base_avatar_id) VALUES (?, ?)",
        (user_id, base_id),
    )
    unlock_avatar_items_for_user(conn, user_id)
    equip_initial_avatar_combo(conn, user_id, resolved_avatar_type)
    return conn.execute("SELECT * FROM user_avatars WHERE user_id = ?", (user_id,)).fetchone()


def ensure_all_user_avatars(conn):
    seed_avatar_catalog(conn)
    for row in conn.execute("SELECT id FROM users ORDER BY id").fetchall():
        ensure_user_avatar(conn, row["id"], avatar_type_for_user(conn, row["id"]))


def avatar_combo_complete(avatar):
    required = ("equipped_hair", "equipped_hair_color", "equipped_top", "equipped_bottom", "equipped_shoes", "equipped_racket")
    return bool(avatar and all(avatar[field] for field in required))


def avatar_type_for_user(conn, user_id, avatar=None):
    profile = conn.execute("SELECT gender FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if profile and profile["gender"] in ("male", "female"):
        return profile["gender"]
    if avatar:
        row = conn.execute("SELECT type FROM avatar_bases WHERE id = ?", (avatar["base_avatar_id"],)).fetchone()
        if row and row["type"] in ("male", "female"):
            return row["type"]
    return "male" if user_id % 2 else "female"


def initial_avatar_options(avatar_type):
    if avatar_type == "female":
        return {
            "hair": ["hair_tied", "hair_female_bun", "hair_female_pony", "hair_female_braid"],
            "hair_color": ["hair_color_dark", "hair_color_brown_beta", "hair_color_light_beta"],
            "top": ["top_female_black", "top_female_white_beta", "top_female_blue_beta"],
            "bottom": ["bottom_female_black", "bottom_female_white", "bottom_female_lime"],
            "shoes": ["shoes_female_white_beta", "shoes_female_mint_beta", "shoes_female_pink_beta"],
            "racket": ["racket_control", "racket_blue_beta", "racket_gold_beta"],
        }
    return {
        "hair": ["hair_short", "hair_male_side", "hair_male_curl", "hair_male_sweep", "hair_male_waves"],
        "hair_color": ["hair_color_dark", "hair_color_brown_beta", "hair_color_light_beta"],
        "top": ["top_graphite", "top_beta_white", "top_beta_lime"],
        "bottom": ["bottom_carbon", "bottom_beta_white", "bottom_beta_navy"],
        "shoes": ["shoes_black_beta", "shoes_white", "shoes_blue_beta"],
        "racket": ["racket_control", "racket_blue_beta", "racket_gold_beta"],
    }


def combination_for_seed(options, seed):
    categories = ("hair", "hair_color", "top", "bottom", "shoes", "racket")
    combo = {}
    value = seed
    for index, category in enumerate(categories):
        choices = options[category]
        combo[category] = choices[(value + index * 3) % len(choices)]
        value = value // max(1, len(choices)) + seed
    return combo


def recent_avatar_signatures(conn, user_id, limit=30):
    rows = conn.execute(
        """
        SELECT ua.equipped_hair, ua.equipped_hair_color, ua.equipped_top, ua.equipped_bottom, ua.equipped_shoes, ua.equipped_racket
        FROM user_avatars ua
        JOIN users u ON u.id = ua.user_id
        WHERE ua.user_id != ?
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return {tuple(row) for row in rows if all(row)}


def avatar_signature_for_codes(conn, combo):
    ids = []
    for category in ("hair", "hair_color", "top", "bottom", "shoes", "racket"):
        row = conn.execute("SELECT id FROM avatar_items WHERE code = ?", (combo[category],)).fetchone()
        ids.append(row["id"] if row else None)
    return tuple(ids)


def choose_initial_avatar_combo(conn, user_id, avatar_type):
    options = initial_avatar_options(avatar_type)
    recent = recent_avatar_signatures(conn, user_id)
    for offset in range(60):
        combo = combination_for_seed(options, user_id + offset)
        signature = avatar_signature_for_codes(conn, combo)
        if signature not in recent:
            return combo
    return combination_for_seed(options, user_id)


def equip_initial_avatar_combo(conn, user_id, avatar_type="male"):
    avatar_type = avatar_type if avatar_type in ("male", "female") else avatar_type_for_user(conn, user_id)
    unlock_avatar_items_for_user(conn, user_id)
    equip_default_items(conn, user_id)
    combo = choose_initial_avatar_combo(conn, user_id, avatar_type)
    for code in combo.values():
        item = conn.execute("SELECT id FROM avatar_items WHERE code = ? AND is_active = 1", (code,)).fetchone()
        if item:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_avatar_items (user_id, avatar_item_id, unlocked_at, equipped)
                VALUES (?, ?, CURRENT_TIMESTAMP, 0)
                """,
                (user_id, item["id"]),
            )
            equip_avatar_item(conn, user_id, item["id"])


def unlock_avatar_items_for_user(conn, user_id, notify=False):
    profile = conn.execute("SELECT xp_total FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not profile:
        return []
    level = xp_level(profile["xp_total"])
    sync_avatar_locks(conn, user_id, level, profile["xp_total"])
    rows = conn.execute(
        """
        SELECT id
        FROM avatar_items
        WHERE is_active = 1
          AND unlock_achievement_id IS NULL
          AND required_level <= ?
          AND required_xp <= ?
          AND id NOT IN (
              SELECT avatar_item_id FROM user_avatar_items WHERE user_id = ?
          )
        """,
        (level, profile["xp_total"], user_id),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_avatar_items (user_id, avatar_item_id, unlocked_at, equipped)
            VALUES (?, ?, CURRENT_TIMESTAMP, 0)
            """,
            (user_id, row["id"]),
        )
    unlocked_ids = [row["id"] for row in rows]
    if notify:
        notify_avatar_unlocks(conn, user_id, unlocked_ids)
    return unlocked_ids


def equip_default_items(conn, user_id):
    avatar = conn.execute("SELECT * FROM user_avatars WHERE user_id = ?", (user_id,)).fetchone()
    if not avatar:
        return
    for category in (
        "face",
        "top",
        "bottom",
        "shoes",
        "racket",
        "frame",
        "background",
        "hair",
        "hair_color",
        "headband",
        "wristband",
        "overgrip",
    ):
        if avatar[AVATAR_CATEGORIES[category]]:
            continue
        item = conn.execute(
            """
            SELECT ai.id
            FROM avatar_items ai
            JOIN user_avatar_items uai ON uai.avatar_item_id = ai.id AND uai.user_id = ?
            WHERE ai.category = ?
            ORDER BY ai.required_level, ai.required_xp, ai.id
            LIMIT 1
            """,
            (user_id, category),
        ).fetchone()
        if item:
            equip_avatar_item(conn, user_id, item["id"])


def equip_avatar_item(conn, user_id, item_id):
    item = conn.execute(
        """
        SELECT ai.*, uai.unlocked_at, uai.earned_at, a.name AS unlock_achievement_name
        FROM avatar_items ai
        LEFT JOIN user_avatar_items uai ON uai.avatar_item_id = ai.id AND uai.user_id = ?
        LEFT JOIN achievements a ON a.id = ai.unlock_achievement_id
        WHERE ai.id = ? AND ai.is_active = 1
        """,
        (user_id, item_id),
    ).fetchone()
    if not item:
        raise ValueError("Item de avatar no disponible.")
    if not (item["unlocked_at"] or item["earned_at"]):
        profile = conn.execute("SELECT xp_total FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
        total_xp = profile["xp_total"] if profile else 0
        if item["unlock_achievement_id"]:
            raise ValueError(f"Este item se desbloquea con el logro {item['unlock_achievement_name']}.")
        xp_missing = max(0, item["required_xp"] - total_xp)
        raise ValueError(f"Este item se desbloquea en Nivel {item['required_level']}. Te faltan {xp_missing} XP.")
    category = item["category"]
    field = AVATAR_CATEGORIES.get(category)
    if not field:
        raise ValueError("Categoria de avatar no soportada.")
    conn.execute(
        "UPDATE user_avatar_items SET equipped = 0 WHERE user_id = ? AND avatar_item_id IN (SELECT id FROM avatar_items WHERE category = ?)",
        (user_id, category),
    )
    conn.execute("UPDATE user_avatar_items SET equipped = 1 WHERE user_id = ? AND avatar_item_id = ?", (user_id, item_id))
    conn.execute(f"UPDATE user_avatars SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (item_id, user_id))


def unequip_avatar_category(conn, user_id, category):
    field = AVATAR_CATEGORIES.get(category)
    if not field:
        raise ValueError("Categoria de avatar no soportada.")
    conn.execute(
        "UPDATE user_avatar_items SET equipped = 0 WHERE user_id = ? AND avatar_item_id IN (SELECT id FROM avatar_items WHERE category = ?)",
        (user_id, category),
    )
    conn.execute(f"UPDATE user_avatars SET {field} = NULL, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))


def set_avatar_base(conn, user_id, base_id):
    row = conn.execute("SELECT id FROM avatar_bases WHERE id = ? AND is_active = 1", (base_id,)).fetchone()
    if not row:
        raise ValueError("Avatar base no disponible.")
    conn.execute("UPDATE user_avatars SET base_avatar_id = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (base_id, user_id))


def avatar_payload(conn, user_id):
    ensure_user_avatar(conn, user_id)
    unlock_avatar_items_for_user(conn, user_id)
    equip_default_items(conn, user_id)
    profile = conn.execute("SELECT xp_total FROM player_profiles WHERE user_id = ?", (user_id,)).fetchone()
    total_xp = profile["xp_total"] if profile else 0
    level = xp_level(total_xp)
    next_level_xp = level * 500
    current_level_xp = (level - 1) * 500
    avatar = conn.execute(
        """
        SELECT ua.*, ab.name AS base_name, ab.type AS base_type, ab.image_path AS base_image_path
        FROM user_avatars ua
        JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        WHERE ua.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    equipped_ids = {
        avatar[field]
        for field in AVATAR_CATEGORIES.values()
        if avatar and avatar[field]
    }
    items = []
    for row in conn.execute(
        """
        SELECT
            ai.*,
            COALESCE(uai.unlocked_at, uai.earned_at) AS unlocked_at,
            COALESCE(uai.equipped, 0) AS equipped,
            a.code AS unlock_achievement_code,
            a.name AS unlock_achievement_name
        FROM avatar_items ai
        LEFT JOIN user_avatar_items uai ON uai.avatar_item_id = ai.id AND uai.user_id = ?
        LEFT JOIN achievements a ON a.id = ai.unlock_achievement_id
        WHERE ai.is_active = 1
        ORDER BY ai.category, ai.required_level, ai.required_xp, ai.id
        """,
        (user_id,),
    ).fetchall():
        item = dict(row)
        item["unlocked"] = bool(item["unlocked_at"])
        item["equipped"] = bool(item["id"] in equipped_ids or item["equipped"])
        item["xp_missing"] = max(0, item["required_xp"] - total_xp)
        item["level_missing"] = max(0, item["required_level"] - level)
        unlock_target = max(item["required_xp"], xp_required_for_level(item["required_level"]))
        item["unlock_target_xp"] = unlock_target
        item["unlock_progress_xp"] = min(total_xp, unlock_target) if unlock_target else 0
        item["unlock_progress_percent"] = 100 if item["unlocked"] else int((item["unlock_progress_xp"] / unlock_target) * 100) if unlock_target else 0
        item["unlock_label"] = f"Logro: {item['unlock_achievement_name']}" if item["unlock_achievement_id"] else f"Nivel {item['required_level']}"
        item["rarity_rank"] = RARITY_ORDER.get(item["rarity"], 1)
        items.append(item)
    bases = [dict(row) for row in conn.execute("SELECT * FROM avatar_bases WHERE is_active = 1 ORDER BY id").fetchall()]
    next_unlocks = sorted(
        [item for item in items if not item["unlocked"] and not item["unlock_achievement_id"]],
        key=lambda item: (item["required_level"], item["required_xp"], item["rarity_rank"], item["id"]),
    )[:3]
    return {
        "avatar": dict(avatar) if avatar else None,
        "bases": bases,
        "items": items,
        "next_unlocks": next_unlocks,
        "level": level,
        "xp": {
            "total": total_xp,
            "current_level_xp": current_level_xp,
            "next_level_xp": next_level_xp,
            "progress": total_xp - current_level_xp,
            "needed": next_level_xp - current_level_xp,
        },
    }


def grant_xp(conn, user_id, season_id, amount, kind, reason, match_id=None):
    before = scalar(conn, "SELECT xp_total FROM player_profiles WHERE user_id = ?", (user_id,)) or 0
    before_level = xp_level(before)
    conn.execute(
        """
        INSERT INTO xp_transactions (user_id, season_id, match_id, amount, kind, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, season_id, match_id, amount, kind, reason),
    )
    conn.execute(
        """
        UPDATE player_profiles
        SET xp_total = xp_total + ?, xp_monthly = xp_monthly + ?
        WHERE user_id = ?
        """,
        (amount, amount, user_id),
    )
    after_level = xp_level(before + amount)
    if after_level > before_level:
        create_notification(
            conn,
            user_id,
            "reward",
            "Has subido de nivel",
            f"Nuevo nivel: {after_level}. Sigue ganando XP para desbloquear más recompensas.",
            "xp",
            season_id,
            priority=2,
            event_key=f"reward:level:{after_level}",
        )
    return unlock_avatar_items_for_user(conn, user_id, notify=True)


def grant_achievement(conn, user_id, code, season_id=None):
    achievement_id = scalar(conn, "SELECT id FROM achievements WHERE code = ?", (code,))
    if not achievement_id:
        return
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO user_achievements (user_id, achievement_id, season_id)
        VALUES (?, ?, ?)
        """,
        (user_id, achievement_id, season_id),
    )
    item_rows = conn.execute("SELECT id FROM avatar_items WHERE unlock_achievement_id = ?", (achievement_id,)).fetchall()
    unlocked_item_ids = []
    for item in item_rows:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO user_avatar_items (user_id, avatar_item_id, unlocked_at, equipped) VALUES (?, ?, CURRENT_TIMESTAMP, 0)",
            (user_id, item["id"]),
        )
        if cursor.rowcount:
            unlocked_item_ids.append(item["id"])
    notify_avatar_unlocks(conn, user_id, unlocked_item_ids)
    return bool(cursor.rowcount if item_rows else cursor.rowcount)


def apply_match_xp(conn, match_id):
    existing = scalar(
        conn,
        "SELECT COUNT(*) FROM xp_transactions WHERE match_id = ? AND kind = 'match'",
        (match_id,),
    )
    if existing:
        return

    row = conn.execute(
        """
        SELECT
            m.season_id, m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.id = ? AND m.status = 'confirmed'
        """,
        (match_id,),
    ).fetchone()
    if not row:
        return

    winning_side = winner_team(row)
    if winning_side not in ("A", "B"):
        return
    team_a = team_ids(row, "A")
    team_b = team_ids(row, "B")
    winners = team_a if winning_side == "A" else team_b
    losers = team_b if winning_side == "A" else team_a

    for user_id in team_a + team_b:
        grant_xp(conn, user_id, row["season_id"], XP_PLAY_VALID, "match", "Partido valido", match_id)
        grant_achievement(conn, user_id, "debut", row["season_id"])

    for user_id in winners:
        grant_xp(conn, user_id, row["season_id"], XP_WIN, "match", "Victoria", match_id)
    for user_id in losers:
        grant_xp(conn, user_id, row["season_id"], XP_LOSS, "match", "Derrota", match_id)

    winner_avg = team_rating_average(conn, winners)
    loser_avg = team_rating_average(conn, losers)
    if winner_avg < loser_avg:
        for user_id in winners:
            grant_achievement(conn, user_id, "giant_killer", row["season_id"])


def apply_monthly_achievements(conn, season_id, ranking_rows, promoted_user_ids):
    for row in ranking_rows:
        if row["rank_position"] <= 3:
            grant_xp(conn, row["user_id"], season_id, XP_TOP_3, "season", "Top 3 mensual")
            grant_achievement(conn, row["user_id"], "top_3", season_id)
            top3_count = scalar(
                conn,
                "SELECT COUNT(*) FROM xp_transactions WHERE user_id = ? AND kind = 'season' AND reason = 'Top 3 mensual'",
                (row["user_id"],),
            ) or 0
            if top3_count >= 2:
                grant_achievement(conn, row["user_id"], "repeat_top_3", season_id)
        if row["played"] >= 10:
            grant_xp(conn, row["user_id"], season_id, XP_TEN_MATCHES, "season", "10 partidos mensuales")
            grant_achievement(conn, row["user_id"], "iron_player", season_id)
        if row["played"] >= 5 and row["losses"] == 0:
            grant_achievement(conn, row["user_id"], "undefeated", season_id)

    for user_id in promoted_user_ids:
        grant_xp(conn, user_id, season_id, XP_PROMOTION, "season", "Ascenso de division")
        grant_achievement(conn, user_id, "promotion", season_id)
        promotion_count = scalar(
            conn,
            "SELECT COUNT(*) FROM promotion_relegation_history WHERE user_id = ? AND movement = 'promotion'",
            (user_id,),
        ) or 0
        if promotion_count >= 2:
            grant_achievement(conn, user_id, "consecutive_promotion", season_id)

    national_ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT d.id
            FROM divisions d
            JOIN league_levels l ON l.id = d.level_id
            WHERE l.scope = 'national'
            """
        ).fetchall()
    ]
    first_local = scalar(conn, "SELECT d.id FROM divisions d WHERE d.name = '1a Local'")
    for row in conn.execute("SELECT user_id, current_division_id FROM player_profiles").fetchall():
        if row["current_division_id"] in national_ids:
            grant_achievement(conn, row["user_id"], "national_path")
        if first_local and row["current_division_id"] == first_local:
            grant_achievement(conn, row["user_id"], "local_legend")
