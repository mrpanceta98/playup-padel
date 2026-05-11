from backend.database import row_to_dict, scalar
from backend.services.competition import public_ranking_rows, ranking_for_group


CARD_FORMATS = {
    "story": {"width": 1080, "height": 1920, "label": "Story"},
    "square": {"width": 1080, "height": 1080, "label": "Square"},
}


def share_card_payload(conn, season, user_id, card_type="status", card_format="story", base_url=""):
    profile = conn.execute(
        """
        SELECT p.user_id, p.display_name, p.rating, p.xp_total, d.name AS division_name,
               g.id AS group_id, g.name AS group_name, ab.image_path AS avatar_base_image
        FROM player_profiles p
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN groups g ON g.id = p.current_group_id
        LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        WHERE p.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not profile:
        raise ValueError("Jugador no encontrado.")
    profile = row_to_dict(profile)
    ranking = []
    row = None
    if season and profile["group_id"]:
        ranking = public_ranking_rows(ranking_for_group(conn, season["id"], profile["group_id"], persist=True))
        row = next((item for item in ranking if item["user_id"] == user_id), None)
    share_url = create_or_update_share_link(conn, user_id, base_url)["url"]
    qr = qr_payload(share_url)
    card_type = card_type if card_type in {"status", "promotion_gap", "promoted", "avatar_unlock", "monthly_challenge"} else "status"
    card_format = card_format if card_format in CARD_FORMATS else "story"
    status = movement_status(row)
    headline = card_headline(conn, user_id, row, ranking, card_type)
    subheadline = card_subheadline(conn, user_id, row, card_type)
    return {
        "type": card_type,
        "format": card_format,
        "dimensions": CARD_FORMATS[card_format],
        "headline": headline,
        "subheadline": subheadline,
        "cta": "Únete a mi liga en PlayUp Padel",
        "share_url": share_url,
        "share_link_saved": True,
        "qr_payload_url": share_url,
        "qr_matrix": qr["matrix"],
        "qr_error": qr["error"],
        "logo_path": "/assets/playup-logo.png",
        "player": {
            "name": profile["display_name"],
            "avatar": profile["avatar_base_image"] or "/assets/avatars/neutral_base.png",
            "division": profile["division_name"] or "3a Local",
            "group": profile["group_name"] or "Liga inicial",
            "rating": profile["rating"],
            "xp_total": profile["xp_total"],
        },
        "competition": {
            "position": row["rank_position"] if row else None,
            "position_label": f"#{row['rank_position']}" if row and row["rank_position"] else "-",
            "points": row["points"] if row else 0,
            "played": row["played"] if row else 0,
            "max_matches": 10,
            "status": status,
            "status_label": status_label(status),
            "promotion_gap_points": promotion_gap_points(row, ranking),
        },
    }


def create_or_update_share_link(conn, user_id, base_url=""):
    ref = str(user_id)
    path = f"/join-league?ref={ref}"
    url = f"{base_url.rstrip('/')}{path}" if base_url else path
    conn.execute(
        """
        INSERT INTO share_links (user_id, kind, ref, url)
        VALUES (?, 'join_league', ?, ?)
        ON CONFLICT(user_id, kind) DO UPDATE SET
            ref = excluded.ref,
            url = excluded.url,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, ref, url),
    )
    return row_to_dict(
        conn.execute(
            "SELECT * FROM share_links WHERE user_id = ? AND kind = 'join_league'",
            (user_id,),
        ).fetchone()
    )


def qr_payload(value):
    try:
        return {"matrix": real_qr_matrix(value), "error": None}
    except Exception as exc:
        return {"matrix": None, "error": str(exc)}


def movement_status(row):
    if not row:
        return "middle"
    return {
        "promotion": "promotion",
        "relegation": "relegation",
    }.get(row["movement_zone"], "middle")


def status_label(status):
    return {
        "promotion": "Zona ascenso",
        "relegation": "Zona descenso",
        "middle": "Zona media",
    }[status]


def promotion_gap_points(row, ranking):
    if not row:
        return None
    if row["rank_position"] <= 3:
        return 0
    promotion_cut = next((item for item in ranking if item["rank_position"] == 3), None)
    if not promotion_cut:
        return None
    return max(1, promotion_cut["points"] + 1 - row["points"])


def card_headline(conn, user_id, row, ranking, card_type):
    gap = promotion_gap_points(row, ranking)
    if card_type == "promoted":
        promoted = latest_promotion(conn, user_id)
        return f"He subido a {promoted['to_division']}" if promoted else "Estoy subiendo en PlayUp Padel"
    if card_type == "avatar_unlock":
        item = latest_avatar_unlock(conn, user_id)
        return f"He desbloqueado {item}" if item else "Mi avatar sigue subiendo"
    if card_type == "monthly_challenge":
        challenge = latest_monthly_reward(conn, user_id)
        return f"He ganado el reto {challenge}" if challenge else "He completado un reto mensual"
    if row and row["movement_zone"] == "promotion":
        return "Estoy en zona de ascenso"
    if gap:
        return f"Me faltan {gap} puntos para subir"
    if row and row["movement_zone"] == "relegation":
        return "Necesito ganar para salir del descenso"
    return "Sigo peleando por el ascenso"


def card_subheadline(conn, user_id, row, card_type):
    if card_type == "promoted":
        promoted = latest_promotion(conn, user_id)
        if promoted:
            return f"{promoted['from_division']} → {promoted['to_division']}"
    if card_type == "avatar_unlock":
        item = latest_avatar_unlock(conn, user_id)
        if item:
            return "Nuevo item desbloqueado en mi Player Card"
    if card_type == "monthly_challenge":
        challenge = latest_monthly_reward(conn, user_id)
        if challenge:
            return "Reto mensual completado"
    if not row:
        return "Primer mes competitivo en PlayUp Padel"
    return f"{row['points']} puntos · {row['played']}/10 partidos"


def latest_promotion(conn, user_id):
    row = conn.execute(
        """
        SELECT fd.name AS from_division, td.name AS to_division
        FROM promotion_relegation_history h
        LEFT JOIN divisions fd ON fd.id = h.from_division_id
        LEFT JOIN divisions td ON td.id = h.to_division_id
        WHERE h.user_id = ? AND h.movement = 'promotion'
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return row_to_dict(row)


def latest_avatar_unlock(conn, user_id):
    return scalar(
        conn,
        """
        SELECT ai.name
        FROM user_avatar_items uai
        JOIN avatar_items ai ON ai.id = uai.avatar_item_id
        WHERE uai.user_id = ?
        ORDER BY COALESCE(uai.unlocked_at, uai.earned_at) DESC, uai.id DESC
        LIMIT 1
        """,
        (user_id,),
    )


def latest_monthly_reward(conn, user_id):
    return scalar(
        conn,
        """
        SELECT mc.title
        FROM user_monthly_challenges umc
        JOIN monthly_challenges mc ON mc.id = umc.monthly_challenge_id
        WHERE umc.user_id = ? AND umc.status = 'claimed'
        ORDER BY umc.claimed_at DESC, umc.id DESC
        LIMIT 1
        """,
        (user_id,),
    )


def real_qr_matrix(value):
    data = value.encode("utf-8")
    version = 5
    size = 21 + 4 * (version - 1)
    data_codewords = 108
    ecc_codewords = 26
    if len(data) > 106:
        raise ValueError("El enlace es demasiado largo para el QR MVP.")
    bits = [0, 1, 0, 0]
    bits.extend(int(bit) for bit in f"{len(data):08b}")
    for byte in data:
        bits.extend(int(bit) for bit in f"{byte:08b}")
    bits.extend([0] * min(4, data_codewords * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    codewords = [int("".join(str(bit) for bit in bits[i : i + 8]), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(codewords) < data_codewords:
        codewords.append(pad[len(codewords) % 2])
    all_codewords = codewords + reed_solomon_remainder(codewords, ecc_codewords)
    modules = [[False for _ in range(size)] for _ in range(size)]
    function = [[False for _ in range(size)] for _ in range(size)]
    add_function_patterns(modules, function, version)
    raw_bits = []
    for codeword in all_codewords:
        raw_bits.extend((codeword >> shift) & 1 for shift in range(7, -1, -1))
    best = None
    for mask in range(8):
        candidate = [row[:] for row in modules]
        place_data(candidate, function, raw_bits, mask)
        add_format_bits(candidate, function, mask)
        penalty = qr_penalty(candidate)
        if best is None or penalty < best[0]:
            best = (penalty, candidate)
    return best[1]


def add_function_patterns(modules, function, version):
    size = len(modules)
    for x, y in ((0, 0), (size - 7, 0), (0, size - 7)):
        add_finder(modules, function, x, y)
    for i in range(size):
        if not function[i][6]:
            set_function(modules, function, 6, i, i % 2 == 0)
        if not function[6][i]:
            set_function(modules, function, i, 6, i % 2 == 0)
    for x, y in ((30, 30),):
        add_alignment(modules, function, x, y)
    set_function(modules, function, 8, 4 * version + 9, True)
    reserve_format(function)


def add_finder(modules, function, left, top):
    size = len(modules)
    for y in range(top - 1, top + 8):
        for x in range(left - 1, left + 8):
            if 0 <= x < size and 0 <= y < size:
                is_border = left <= x < left + 7 and top <= y < top + 7 and (x in (left, left + 6) or y in (top, top + 6))
                is_center = left + 2 <= x <= left + 4 and top + 2 <= y <= top + 4
                set_function(modules, function, x, y, is_border or is_center)


def add_alignment(modules, function, center_x, center_y):
    for y in range(center_y - 2, center_y + 3):
        for x in range(center_x - 2, center_x + 3):
            set_function(modules, function, x, y, max(abs(x - center_x), abs(y - center_y)) != 1)


def reserve_format(function):
    size = len(function)
    for i in range(9):
        if i != 6:
            function[8][i] = True
            function[i][8] = True
    for i in range(8):
        function[8][size - 1 - i] = True
        function[size - 1 - i][8] = True


def set_function(modules, function, x, y, value):
    modules[y][x] = bool(value)
    function[y][x] = True


def place_data(modules, function, bits, mask):
    size = len(modules)
    bit_index = 0
    upward = True
    x = size - 1
    while x > 0:
        if x == 6:
            x -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for y in rows:
            for dx in (0, 1):
                xx = x - dx
                if function[y][xx]:
                    continue
                bit = bits[bit_index] if bit_index < len(bits) else 0
                modules[y][xx] = bool(bit) ^ mask_bit(mask, xx, y)
                bit_index += 1
        upward = not upward
        x -= 2


def add_format_bits(modules, function, mask):
    size = len(modules)
    bits = format_bits(mask)
    for i in range(15):
        bit = ((bits >> i) & 1) == 1
        x1, y1 = (8, i) if i < 6 else (8, i + 1) if i < 8 else (8, size - 15 + i)
        x2, y2 = (size - 1 - i, 8) if i < 8 else (14 - i, 8)
        modules[y1][x1] = bit
        modules[y2][x2] = bit
        function[y1][x1] = True
        function[y2][x2] = True
    modules[size - 8][8] = True
    function[size - 8][8] = True


def format_bits(mask):
    data = (1 << 3) | mask
    value = data << 10
    generator = 0x537
    for shift in range(14, 9, -1):
        if (value >> shift) & 1:
            value ^= generator << (shift - 10)
    return ((data << 10) | value) ^ 0x5412


def mask_bit(mask, x, y):
    return (
        (x + y) % 2 == 0 if mask == 0 else
        y % 2 == 0 if mask == 1 else
        x % 3 == 0 if mask == 2 else
        (x + y) % 3 == 0 if mask == 3 else
        ((y // 2) + (x // 3)) % 2 == 0 if mask == 4 else
        ((x * y) % 2 + (x * y) % 3) == 0 if mask == 5 else
        (((x * y) % 2 + (x * y) % 3) % 2) == 0 if mask == 6 else
        (((x + y) % 2 + (x * y) % 3) % 2) == 0
    )


def reed_solomon_remainder(data, degree):
    generator = rs_generator_poly(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(generator):
            result[i] ^= gf_multiply(coefficient, factor)
    return result


def rs_generator_poly(degree):
    poly = [1]
    for i in range(degree):
        poly = poly_multiply(poly, [1, gf_pow(2, i)])
    return poly[1:]


def poly_multiply(left, right):
    result = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] ^= gf_multiply(a, b)
    return result


def gf_multiply(left, right):
    product = 0
    while right:
        if right & 1:
            product ^= left
        left <<= 1
        if left & 0x100:
            left ^= 0x11D
        right >>= 1
    return product


def gf_pow(value, power):
    result = 1
    for _ in range(power):
        result = gf_multiply(result, value)
    return result


def qr_penalty(matrix):
    size = len(matrix)
    penalty = 0
    for row in matrix:
        penalty += run_penalty(row)
    for x in range(size):
        penalty += run_penalty([matrix[y][x] for y in range(size)])
    for y in range(size - 1):
        for x in range(size - 1):
            color = matrix[y][x]
            if matrix[y][x + 1] == color and matrix[y + 1][x] == color and matrix[y + 1][x + 1] == color:
                penalty += 3
    dark = sum(1 for row in matrix for value in row if value)
    percent = dark * 100 // (size * size)
    penalty += abs(percent - 50) // 5 * 10
    return penalty


def run_penalty(values):
    penalty = 0
    run_color = values[0]
    run_length = 1
    for value in values[1:]:
        if value == run_color:
            run_length += 1
        else:
            if run_length >= 5:
                penalty += 3 + run_length - 5
            run_color = value
            run_length = 1
    if run_length >= 5:
        penalty += 3 + run_length - 5
    return penalty
