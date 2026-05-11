import json
import mimetypes
import os
import re
import traceback
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.auth import create_token, hash_password, verify_password, verify_token
from backend.database import ROOT, connect, row_to_dict, rows_to_dicts, scalar
from backend.seed import init_data
from backend.services.competition import (
    close_monthly_season,
    divisions,
    parse_score,
    public_ranking_rows,
    ranking_for_group,
    recalc_all_rankings,
)
from backend.services.activation import (
    create_quick_play_now_match,
    join_match_request,
    play_now_recommendation,
    set_player_availability,
    touch_player_activity,
)
from backend.services.challenges import (
    accept_challenge,
    complete_challenge_for_match,
    create_automatic_challenge,
    create_open_challenge,
    list_challenges,
    reject_challenge,
    submit_challenge_result,
    suggested_rivals,
    weekly_challenges,
)
from backend.services.division_structure import lowest_division_id
from backend.services.gamification import (
    apply_match_xp,
    avatar_payload,
    ensure_user_avatar,
    equip_avatar_item,
    grant_achievement,
    grant_xp,
    set_avatar_base,
    unequip_avatar_category,
    xp_level,
)
from backend.services.free_matches import (
    accept_free_match_invitation,
    create_free_match,
    free_matches_for_user,
    generate_free_match_invitations,
    invitation_context,
    link_external_player,
)
from backend.services.grouping import assign_new_player_to_group
from backend.services.grouping import rebalance_division_if_safe
from backend.services.match_teams import first_or_none, loser_team, participant_ids, player_team, team_ids, team_score_stats, winner_team
from backend.services.monthly_challenges import claim_monthly_challenge, list_monthly_challenges
from backend.services.notifications import (
    generate_context_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    unread_count,
)
from backend.services.player_identity import player_identity
from backend.services.rating import apply_rating_for_match
from backend.services.share_cards import share_card_payload


FRONTEND_DIR = ROOT / "frontend"
ASSETS_DIR = ROOT / "assets"
APP_VERSION = "playup-local-mvp"
APP_ENV = os.environ.get("PLAYUP_ENV", "local")
APP_HOST = os.environ.get("PLAYUP_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
APP_PORT = int(os.environ.get("PORT") or os.environ.get("PLAYUP_PORT", "4173"))
DEFAULT_ALLOWED_ORIGINS = {
    "capacitor://localhost",
    "ionic://localhost",
    "http://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "https://app.playuppadel.com",
}
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("PLAYUP_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
} or DEFAULT_ALLOWED_ORIGINS


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def active_season(conn):
    return conn.execute("SELECT * FROM seasons WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()


def log_error(conn, error_type, message, stack_trace="", url="", user_id=None, resolved=False):
    conn.execute(
        """
        INSERT INTO error_logs (user_id, type, message, stack_trace, url, resolved)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, error_type, str(message)[:1000], str(stack_trace or "")[:6000], str(url or "")[:500], int(bool(resolved))),
    )


def user_id_from_headers(conn, headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = verify_token(auth.replace("Bearer ", "", 1))
    except ValueError:
        return None
    if not payload:
        return None
    user_id = payload.get("sub")
    return user_id if scalar(conn, "SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)) else None


def error_type_for_path(path, default="api_error"):
    if path.startswith("/api/auth/"):
        return "auth_error"
    if "/matches" in path or "/play-now/create-match" in path:
        return "match_error"
    if "/share-card" in path:
        return "share_card_error"
    if "/admin" in path:
        return "admin_error"
    return default


def profile_for_user(conn, user_id):
    return conn.execute(
        """
        SELECT
            u.id AS user_id, u.email, u.role, p.display_name, p.level_guess, p.lat, p.lng,
            p.gender, p.availability_text,
            p.rating, p.xp_total, p.xp_monthly, p.avatar_outfit, p.avatar_racket,
            p.avatar_frame, p.avatar_background, p.streak_months, p.playtomic_id,
            p.available_for_play, p.availability_updated_at, p.last_active_at,
            p.onboarding_completed_at, p.initial_mission_claimed_at,
            ab.id AS avatar_base_id, ab.type AS avatar_base_type, ab.image_path AS avatar_base_image,
            frame.name AS equipped_frame_name, background.name AS equipped_background_name,
            effect.name AS equipped_effect_name,
            l.city, l.region, l.country, c.name AS club,
            d.id AS division_id, d.name AS division_name,
            g.id AS group_id, g.name AS group_name,
            pc.status AS playtomic_status
        FROM users u
        JOIN player_profiles p ON p.user_id = u.id
        JOIN locations l ON l.id = p.location_id
        LEFT JOIN clubs c ON c.id = p.club_id
        LEFT JOIN divisions d ON d.id = p.current_division_id
        LEFT JOIN groups g ON g.id = p.current_group_id
        LEFT JOIN playtomic_connections pc ON pc.user_id = u.id
        LEFT JOIN user_avatars ua ON ua.user_id = u.id
        LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
        LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
        LEFT JOIN avatar_items background ON background.id = ua.equipped_background
        LEFT JOIN avatar_items effect ON effect.id = ua.equipped_effect
        WHERE u.id = ?
        """,
        (user_id,),
    ).fetchone()


def require_user(conn, headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(401, "No autenticado.")
    user_id = verify_token(auth.replace("Bearer ", "", 1))
    if not user_id:
        raise ApiError(401, "Sesion caducada.")
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise ApiError(401, "Usuario no encontrado.")
    touch_player_activity(conn, user["id"])
    return user


def require_admin(user):
    if user["role"] != "admin":
        raise ApiError(403, "Solo administradores.")


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    send_cors_headers(handler)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def allowed_origin(origin):
    if not origin:
        return ""
    if "*" in ALLOWED_ORIGINS:
        return origin
    return origin if origin in ALLOWED_ORIGINS else ""


def send_cors_headers(handler):
    origin = allowed_origin(handler.headers.get("Origin", ""))
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Credentials", "true")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def location_id_for_city(conn, city):
    row = conn.execute("SELECT id FROM locations WHERE city = ?", (city,)).fetchone()
    if not row:
        raise ApiError(400, "Ciudad no soportada en el MVP.")
    return row["id"]


def default_club_id(conn, location_id, club_name):
    row = conn.execute("SELECT id FROM clubs WHERE name = ?", (club_name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO clubs (name, location_id) VALUES (?, ?)", (club_name, location_id))
    return cursor.lastrowid


def starting_division_id(conn):
    return lowest_division_id(conn)


def player_card(conn, user_id):
    profile = profile_for_user(conn, user_id)
    if not profile:
        return None
    level = xp_level(profile["xp_total"])
    return {
        "user_id": profile["user_id"],
        "display_name": profile["display_name"],
        "division_name": profile["division_name"],
        "group_name": profile["group_name"],
        "level_guess": profile["level_guess"],
        "rating": profile["rating"],
        "xp_total": profile["xp_total"],
        "xp_level": level,
        "avatar_base_id": profile["avatar_base_id"],
        "avatar_base_type": profile["avatar_base_type"],
        "avatar_base_image": profile["avatar_base_image"],
        "equipped_frame_name": profile["equipped_frame_name"],
        "equipped_background_name": profile["equipped_background_name"],
        "equipped_effect_name": profile["equipped_effect_name"],
        "available_for_play": bool(profile["available_for_play"]),
        "avatar_outfit": profile["avatar_outfit"],
        "avatar_frame": profile["avatar_frame"],
    }


def match_player_reward(conn, match_id, player, points=0):
    xp = scalar(
        conn,
        "SELECT COALESCE(SUM(amount), 0) FROM xp_transactions WHERE match_id = ? AND user_id = ? AND kind = 'match'",
        (match_id, player["user_id"]),
    )
    return {**player, "match_points": points, "match_xp": xp or 0}


def match_status_label(status):
    return {
        "pending_confirmation": "Pendiente",
        "confirmed": "Confirmado",
        "conflict": "En disputa",
    }.get(status, status)


def match_payload(conn, row, current_user_id):
    result = conn.execute("SELECT * FROM match_results WHERE match_id = ?", (row["id"],)).fetchone()
    merged = dict(row)
    if result:
        merged.update(dict(result))
    team_a = team_ids(merged, "A")
    team_b = team_ids(merged, "B")
    my_team = player_team(merged, current_user_id)
    creator_team = player_team(merged, row["created_by"])
    pending_for_me = (
        row["status"] == "pending_confirmation"
        and current_user_id in participant_ids(merged)
        and (current_user_id != row["created_by"])
        and (my_team != creator_team)
    )
    winning_side = winner_team(merged)
    is_confirmed = row["status"] == "confirmed"
    team_a_stats = team_score_stats(merged, "A") if result else None
    team_b_stats = team_score_stats(merged, "B") if result else None
    team_a_points = 3 if is_confirmed and winning_side == "A" else 1 if is_confirmed and winning_side == "B" else 0
    team_b_points = 3 if is_confirmed and winning_side == "B" else 1 if is_confirmed and winning_side == "A" else 0
    team_a_cards = [match_player_reward(conn, row["id"], player_card(conn, user_id), team_a_points) for user_id in team_a]
    team_b_cards = [match_player_reward(conn, row["id"], player_card(conn, user_id), team_b_points) for user_id in team_b]
    return {
        "id": row["id"],
        "season_id": row["season_id"],
        "group_id": row["group_id"],
        "player_a_id": row["player_a_id"],
        "player_b_id": row["player_b_id"],
        "player_a": player_card(conn, row["player_a_id"])["display_name"],
        "player_b": player_card(conn, row["player_b_id"])["display_name"],
        "team_a": team_a_cards,
        "team_b": team_b_cards,
        "team_a_label": " / ".join(player_card(conn, user_id)["display_name"] for user_id in team_a),
        "team_b_label": " / ".join(player_card(conn, user_id)["display_name"] for user_id in team_b),
        "source": row["source"],
        "status": row["status"],
        "status_label": match_status_label(row["status"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "score": result["score"] if result else "",
        "winner_id": result["winner_id"] if result else None,
        "winner_team": winning_side,
        "winner": f"Equipo {winning_side}" if winning_side else "",
        "team_a_points": team_a_points,
        "team_b_points": team_b_points,
        "team_a_stats": team_a_stats,
        "team_b_stats": team_b_stats,
        "conflict_note": result["conflict_note"] if result else "",
        "pending_for_me": pending_for_me,
        "is_discarded": False,
    }


def group_for_user(conn, user_id):
    season = active_season(conn)
    if not season:
        raise ApiError(400, "No hay temporada activa.")
    row = conn.execute(
        """
        SELECT g.*
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        WHERE gm.user_id = ? AND gm.season_id = ? AND gm.active = 1
        LIMIT 1
        """,
        (user_id, season["id"]),
    ).fetchone()
    if not row:
        raise ApiError(404, "El jugador no tiene grupo activo.")
    return season, row


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_OPTIONS(self):
        self.send_response(204)
        send_cors_headers(self)
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def handle_request(self, method):
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                with connect() as conn:
                    payload = self.route_api(conn, method, parsed.path, parse_qs(parsed.query))
                    conn.commit()
                json_response(self, 200, payload)
            else:
                self.serve_static(parsed.path)
        except ApiError as exc:
            self.safe_log_error(error_type_for_path(parsed.path), exc.message, "", parsed.path)
            json_response(self, exc.status, {"error": exc.message})
        except Exception as exc:
            self.safe_log_error("backend_error", str(exc), traceback.format_exc(), parsed.path)
            json_response(self, 500, {"error": str(exc)})

    def safe_log_error(self, error_type, message, stack_trace="", url=""):
        try:
            with connect() as conn:
                log_error(conn, error_type, message, stack_trace, url, user_id_from_headers(conn, self.headers))
                conn.commit()
        except Exception:
            return

    def serve_static(self, path):
        if path == "/":
            target = FRONTEND_DIR / "index.html"
        elif path.startswith("/assets/"):
            target = ASSETS_DIR / path.replace("/assets/", "", 1)
        else:
            target = FRONTEND_DIR / path.lstrip("/")
        if not target.exists() or not target.is_file():
            target = FRONTEND_DIR / "index.html"
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        send_cors_headers(self)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def route_api(self, conn, method, path, query):
        if method == "POST" and path == "/api/error-logs":
            return self.client_error_log(conn)
        if method == "GET" and path == "/api/status":
            return {"status": "ok", "version": APP_VERSION, "environment": APP_ENV}
        if method == "POST" and path == "/api/feedback":
            return self.client_feedback(conn)
        if method == "POST" and path == "/api/auth/register":
            return self.register(conn)
        if method == "POST" and path == "/api/auth/login":
            return self.login(conn)
        invitation = re.match(r"^/api/invitations/([^/]+)$", path)
        if method == "GET" and invitation:
            return self.invitation(conn, invitation.group(1))
        invitation_register = re.match(r"^/api/invitations/([^/]+)/register$", path)
        if method == "POST" and invitation_register:
            return self.register_from_invitation(conn, invitation_register.group(1))

        user = require_user(conn, self.headers)

        if method == "GET" and path == "/api/auth/me":
            return {"user": row_to_dict(profile_for_user(conn, user["id"]))}
        if method == "GET" and path == "/api/bootstrap":
            return self.bootstrap(conn, user)
        if method == "GET" and path == "/api/home":
            return self.home(conn, user)
        if method == "GET" and path == "/api/share-card":
            return self.share_card(conn, user, query)
        if method == "GET" and path == "/api/play-now":
            return self.play_now(conn, user)
        if method == "POST" and path == "/api/availability":
            return self.update_availability(conn, user)
        if method == "POST" and path == "/api/starter-mission/claim":
            return self.claim_starter_mission(conn, user)
        if method == "POST" and path == "/api/play-now/create-match":
            return self.create_play_now_match(conn, user)
        if method == "GET" and path == "/api/profile":
            return {"profile": row_to_dict(profile_for_user(conn, user["id"]))}
        if method == "PUT" and path == "/api/profile":
            return self.update_profile(conn, user)
        if method == "GET" and path == "/api/my-league":
            return self.my_league(conn, user)
        if method == "GET" and path == "/api/matches":
            return self.matches(conn, user)
        if method == "POST" and path == "/api/matches":
            return self.create_match(conn, user)
        if method == "POST" and path == "/api/free-matches":
            return self.create_free_match(conn, user)
        free_match_invitations = re.match(r"^/api/free-matches/(\d+)/invitations$", path)
        if method == "POST" and free_match_invitations:
            return self.free_match_invitations(conn, user, int(free_match_invitations.group(1)))
        external_link = re.match(r"^/api/external-players/(\d+)/link$", path)
        if method == "POST" and external_link:
            return self.link_external_player(conn, user, int(external_link.group(1)))
        if method == "GET" and path == "/api/challenges":
            return self.challenges(conn, user)
        if method == "POST" and path == "/api/challenges":
            return self.create_challenge(conn, user)
        monthly_claim = re.match(r"^/api/monthly-challenges/(\d+)/claim$", path)
        if method == "POST" and monthly_claim:
            return self.claim_monthly_challenge(conn, user, int(monthly_claim.group(1)))
        if method == "GET" and path == "/api/notifications":
            season = active_season(conn)
            if season:
                generate_context_notifications(conn, season["id"], user["id"])
            return {"notifications": list_notifications(conn, user["id"]), "unread_count": unread_count(conn, user["id"])}
        notification_read = re.match(r"^/api/notifications/(\d+)/read$", path)
        if method == "POST" and notification_read:
            mark_notification_read(conn, user["id"], int(notification_read.group(1)))
            return {"notifications": list_notifications(conn, user["id"]), "unread_count": unread_count(conn, user["id"])}
        if method == "POST" and path == "/api/notifications/read-all":
            mark_all_notifications_read(conn, user["id"])
            return {"notifications": list_notifications(conn, user["id"]), "unread_count": unread_count(conn, user["id"])}
        if method == "GET" and path == "/api/leaderboard":
            return self.leaderboard(conn, query)
        if method == "GET" and path == "/api/progress":
            return self.progress(conn, user)
        if method == "GET" and path == "/api/achievements":
            return self.achievements(conn, user)
        if method == "GET" and path == "/api/avatar":
            return self.avatar(conn, user)
        if method == "PUT" and path == "/api/avatar":
            return self.update_avatar(conn, user)
        if method == "GET" and path == "/api/playtomic":
            return self.playtomic(conn, user)
        if method == "PUT" and path == "/api/playtomic":
            return self.update_playtomic(conn, user)

        confirm = re.match(r"^/api/matches/(\d+)/confirm$", path)
        if method == "POST" and confirm:
            return self.confirm_match(conn, user, int(confirm.group(1)))

        conflict = re.match(r"^/api/matches/(\d+)/conflict$", path)
        if method == "POST" and conflict:
            return self.conflict_match(conn, user, int(conflict.group(1)))

        challenge_action = re.match(r"^/api/challenges/(\d+)/(accept|reject|submit-result)$", path)
        if method == "POST" and challenge_action:
            return self.challenge_action(conn, user, int(challenge_action.group(1)), challenge_action.group(2))

        match_request_join = re.match(r"^/api/match-requests/(\d+)/join$", path)
        if method == "POST" and match_request_join:
            return self.join_match_request(conn, user, int(match_request_join.group(1)))

        if path.startswith("/api/admin"):
            require_admin(user)
            return self.admin(conn, method, path, user)

        raise ApiError(404, "Endpoint no encontrado.")

    def client_error_log(self, conn):
        body = read_json(self)
        user_id = user_id_from_headers(conn, self.headers)
        log_error(
            conn,
            body.get("type", "frontend_error"),
            body.get("message", "Error frontend"),
            body.get("stack_trace", ""),
            body.get("url", ""),
            user_id,
        )
        return {"logged": True}

    def client_feedback(self, conn):
        body = read_json(self)
        message = str(body.get("message", "")).strip()
        if not message:
            raise ApiError(400, "Cuéntanos brevemente qué ha pasado.")
        rating = body.get("rating")
        try:
            rating = int(rating) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        if rating is not None:
            rating = max(1, min(5, rating))
        user_id = user_id_from_headers(conn, self.headers)
        conn.execute(
            """
            INSERT INTO beta_feedback (user_id, type, rating, message, url, user_agent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                str(body.get("type", "feedback"))[:80],
                rating,
                message[:1500],
                str(body.get("url", ""))[:500],
                self.headers.get("User-Agent", "")[:500],
            ),
        )
        if body.get("type") == "bug":
            log_error(conn, "beta_bug_report", message, "", body.get("url", ""), user_id)
        return {"received": True, "message": "Gracias. Hemos recibido tu feedback de beta."}

    def register(self, conn):
        body = read_json(self)
        user_id = self.create_player_account(conn, body)
        token = create_token(user_id)
        return {"token": token, "user": row_to_dict(profile_for_user(conn, user_id))}

    def create_player_account(self, conn, body, defaults=None):
        defaults = defaults or {}
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")
        name = (body.get("display_name") or defaults.get("display_name") or "").strip()
        gender = (body.get("gender") or body.get("avatar_type") or "").strip()
        if gender not in ("male", "female"):
            raise ApiError(400, "Elige genero: Hombre o Mujer.")
        city = (body.get("city") or defaults.get("city") or "").strip()
        club = (body.get("club") or defaults.get("club") or "Central Padel").strip() or "Central Padel"
        if not email or not password or not name:
            raise ApiError(400, "Nombre, email y password son obligatorios.")
        if not city:
            raise ApiError(400, "La ciudad es obligatoria.")
        if body.get("level_guess") not in ("Principiante", "Intermedio", "Avanzado"):
            raise ApiError(400, "Nivel aproximado no valido.")
        if scalar(conn, "SELECT id FROM users WHERE email = ?", (email,)):
            raise ApiError(400, "Ya existe una cuenta con ese email.")

        location_id = location_id_for_city(conn, city)
        location = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
        club_id = default_club_id(conn, location_id, club)
        division_id = starting_division_id(conn)
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'player')",
            (email, hash_password(password)),
        )
        user_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO player_profiles
            (user_id, display_name, gender, location_id, club_id, level_guess, lat, lng, current_division_id, availability_text, onboarding_completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                user_id,
                name,
                gender,
                location_id,
                club_id,
                body.get("level_guess"),
                float(body.get("lat", location["lat"])),
                float(body.get("lng", location["lng"])),
                division_id,
                body.get("availability_text", ""),
            ),
        )
        ensure_user_avatar(conn, user_id, gender)
        conn.execute(
            "INSERT INTO playtomic_connections (user_id, playtomic_id, status) VALUES (?, ?, ?)",
            (user_id, body.get("playtomic_id", ""), "pending" if body.get("playtomic_id") else "not_connected"),
        )
        season = active_season(conn)
        assign_new_player_to_group(conn, user_id, division_id, season["id"])
        if body.get("available_for_play"):
            set_player_availability(conn, season["id"], user_id, True, body.get("availability_text") or "Disponible tras completar onboarding.")
        return user_id

    def invitation(self, conn, token):
        try:
            return {"invitation": invitation_context(conn, token)}
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc

    def register_from_invitation(self, conn, token):
        try:
            context = invitation_context(conn, token)
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc
        inviter = profile_for_user(conn, context["invited_by"])
        body = read_json(self)
        defaults = {
            "display_name": context["external_player_name"],
            "city": inviter["city"] if inviter else "Madrid",
            "club": inviter["club"] if inviter else "Central Padel",
        }
        user_id = self.create_player_account(conn, body, defaults)
        accepted = accept_free_match_invitation(conn, token, user_id)
        return {
            "token": create_token(user_id),
            "user": row_to_dict(profile_for_user(conn, user_id)),
            "invitation": invitation_context(conn, token),
            **accepted,
        }

    def login(self, conn):
        body = read_json(self)
        row = conn.execute("SELECT * FROM users WHERE email = ?", (body.get("email", "").strip().lower(),)).fetchone()
        if not row or not verify_password(body.get("password", ""), row["password_hash"]):
            raise ApiError(401, "Credenciales incorrectas.")
        return {"token": create_token(row["id"]), "user": row_to_dict(profile_for_user(conn, row["id"]))}

    def bootstrap(self, conn, user):
        season = active_season(conn)
        if season:
            generate_context_notifications(conn, season["id"], user["id"])
        return {
            "user": row_to_dict(profile_for_user(conn, user["id"])),
            "season": row_to_dict(season),
            "locations": rows_to_dicts(conn.execute("SELECT * FROM locations ORDER BY city").fetchall()),
            "clubs": rows_to_dicts(conn.execute("SELECT * FROM clubs ORDER BY name").fetchall()),
            "divisions": divisions(conn),
            "notifications": list_notifications(conn, user["id"], limit=5),
            "unread_notifications": unread_count(conn, user["id"]),
        }

    def home(self, conn, user):
        season, group = group_for_user(conn, user["id"])
        generate_context_notifications(conn, season["id"], user["id"])
        ranking = public_ranking_rows(ranking_for_group(conn, season["id"], group["id"], persist=True))
        me = next((row for row in ranking if row["user_id"] == user["id"]), None)
        profile = row_to_dict(profile_for_user(conn, user["id"]))
        last_results = latest_results(conn, season["id"], user["id"])
        avatar_data = avatar_payload(conn, user["id"])
        return {
            "profile": profile,
            "season": row_to_dict(season),
            "group": row_to_dict(group),
            "ranking_entry": me,
            "mini_ranking": mini_ranking_around_user(ranking, user["id"]),
            "status": competitive_status(me),
            "matches_progress": {"played": me["played"] if me else 0, "max": 10},
            "level": xp_level(profile["xp_total"]),
            "avatar_progress": {
                "level": avatar_data["level"],
                "xp": avatar_data["xp"],
                "next_unlocks": avatar_data["next_unlocks"],
            },
            "promotion_gap": promotion_gap(me, ranking),
            "season_feedback": season_promotion_feedback(conn, user["id"]),
            "next_objective": next_objective(me, ranking),
            "competitive_message": competitive_message(me, ranking),
            "last_results": last_results[:5],
            "recent_activity": recent_group_activity(conn, season["id"], group["id"], user["id"]),
            "current_streak": current_streak(last_results),
            "recommended_rivals": suggested_rivals(conn, season["id"], user["id"], limit=4),
            "play_now": play_now_recommendation(conn, season["id"], user["id"]),
            "upcoming_challenges": upcoming_challenges(conn, season["id"], user["id"]),
            "pending_results": pending_results(conn, season["id"], user["id"]),
            "is_new_player": is_new_player(conn, season["id"], user["id"], me),
            "starter_checklist": starter_checklist(conn, season["id"], user["id"], profile),
            "starter_mission": starter_mission(conn, season["id"], user["id"], profile),
        }

    def play_now(self, conn, user):
        season = active_season(conn)
        return play_now_recommendation(conn, season["id"], user["id"])

    def share_card(self, conn, user, query):
        season = active_season(conn)
        host = self.headers.get("Host", "")
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        base_url = f"{proto}://{host}" if host else ""
        try:
            card = share_card_payload(
                conn,
                season,
                user["id"],
                query.get("type", ["status"])[0],
                query.get("format", ["story"])[0],
                base_url,
            )
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"card": card}

    def claim_starter_mission(self, conn, user):
        season = active_season(conn)
        try:
            return claim_initial_mission(conn, season["id"], user["id"])
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

    def update_availability(self, conn, user):
        body = read_json(self)
        season = active_season(conn)
        try:
            status = set_player_availability(
                conn,
                season["id"],
                user["id"],
                bool(body.get("available")),
                body.get("message", ""),
            )
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"availability": status, "play_now": play_now_recommendation(conn, season["id"], user["id"])}

    def join_match_request(self, conn, user, request_id):
        try:
            join_match_request(conn, request_id, user["id"])
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        season = active_season(conn)
        return {"joined": True, "play_now": play_now_recommendation(conn, season["id"], user["id"])}

    def create_play_now_match(self, conn, user):
        body = read_json(self)
        season = active_season(conn)
        try:
            created = create_quick_play_now_match(
                conn, season["id"], user["id"], body.get("partner_id"), body.get("rival_ids", [])
            )
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {
            **created,
            "play_now": play_now_recommendation(conn, season["id"], user["id"]),
            "feedback": {
                "type": "match_created",
                "title": "Partido creado",
                "message": "Introduce el resultado cuando terminéis.",
                "summary": created["summary"],
                "team_a": created["team_a"],
                "team_b": created["team_b"],
                "ranking_label": "Próximo paso: resultado",
            },
        }

    def update_profile(self, conn, user):
        body = read_json(self)
        location_id = location_id_for_city(conn, body.get("city", "Madrid"))
        location = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
        club_id = default_club_id(conn, location_id, body.get("club", "Central Padel"))
        conn.execute(
            """
            UPDATE player_profiles
            SET display_name = ?, location_id = ?, club_id = ?, level_guess = ?, lat = ?, lng = ?, playtomic_id = ?
            WHERE user_id = ?
            """,
            (
                body.get("display_name", ""),
                location_id,
                club_id,
                body.get("level_guess", "Intermedio"),
                float(body.get("lat", location["lat"])),
                float(body.get("lng", location["lng"])),
                body.get("playtomic_id", ""),
                user["id"],
            ),
        )
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (body.get("email", "").strip().lower(), user["id"]))
        conn.execute(
            """
            UPDATE playtomic_connections
            SET playtomic_id = ?, status = ?
            WHERE user_id = ?
            """,
            (body.get("playtomic_id", ""), body.get("playtomic_status", "not_connected"), user["id"]),
        )
        return {"profile": row_to_dict(profile_for_user(conn, user["id"]))}

    def my_league(self, conn, user):
        season, group = group_for_user(conn, user["id"])
        members = rows_to_dicts(
            conn.execute(
                """
                SELECT p.user_id, p.display_name, p.rating, l.city, l.region, c.name AS club,
                       ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
                FROM group_members gm
                JOIN player_profiles p ON p.user_id = gm.user_id
                JOIN locations l ON l.id = p.location_id
                LEFT JOIN clubs c ON c.id = p.club_id
                LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
                LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
                LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
                WHERE gm.group_id = ? AND gm.active = 1
                ORDER BY p.rating DESC
                """,
                (group["id"],),
            ).fetchall()
        )
        ranking = public_ranking_rows(ranking_for_group(conn, season["id"], group["id"], persist=True))
        return {"season": row_to_dict(season), "group": row_to_dict(group), "members": members, "ranking": ranking}

    def matches(self, conn, user):
        season, group = group_for_user(conn, user["id"])
        rows = conn.execute(
            """
            SELECT *
            FROM matches
            WHERE season_id = ? AND group_id = ?
              AND (? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id) OR ? = 'admin')
            ORDER BY created_at DESC, id DESC
            """,
            (season["id"], group["id"], user["id"], user["role"]),
        ).fetchall()
        payload = [match_payload(conn, row, user["id"]) for row in rows]
        ranking = ranking_for_group(conn, season["id"], group["id"], persist=True)
        discarded_ids = set()
        for row in ranking:
            if row["user_id"] == user["id"]:
                discarded_ids = set(row["discarded_match_ids"])
        for item in payload:
            item["is_discarded"] = item["id"] in discarded_ids
        players = rows_to_dicts(
            conn.execute(
                """
                SELECT p.user_id, p.display_name, p.rating, p.level_guess, d.name AS division_name,
                       ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
                FROM group_members gm
                JOIN player_profiles p ON p.user_id = gm.user_id
                LEFT JOIN divisions d ON d.id = p.current_division_id
                LEFT JOIN user_avatars ua ON ua.user_id = p.user_id
                LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
                LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
                WHERE gm.group_id = ? AND gm.user_id != ?
                ORDER BY p.display_name
                """,
                (group["id"], user["id"]),
            ).fetchall()
        )
        return {"matches": payload, "free_matches": free_matches_for_user(conn, user["id"]), "players": players, "opponents": players}

    def create_free_match(self, conn, user):
        season = active_season(conn)
        try:
            created = create_free_match(conn, season["id"], user["id"], read_json(self))
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {
            **created,
            "feedback": {
                "type": "challenge_reward",
                "title": "Partido libre registrado",
                "message": "Suma XP y estadisticas personales, pero no altera la liga oficial.",
                "xp_gained": created["xp_gained"],
                "reward_item": "Invitacion pendiente",
                "achievement": "Partido libre",
                "ranking_label": "No afecta ranking",
            },
            "free_matches": free_matches_for_user(conn, user["id"]),
        }

    def free_match_invitations(self, conn, user, free_match_id):
        host = self.headers.get("Host", "")
        proto = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        base_url = f"{proto}://{host}" if host else ""
        try:
            invitations = generate_free_match_invitations(conn, free_match_id, user["id"], base_url)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"invitations": invitations, "free_matches": free_matches_for_user(conn, user["id"])}

    def link_external_player(self, conn, user, external_player_id):
        body = read_json(self)
        try:
            linked = link_external_player(conn, external_player_id, int(body.get("user_id")), user["id"])
        except (TypeError, ValueError) as exc:
            raise ApiError(400, str(exc)) from exc
        return {"external_player": linked}

    def challenges(self, conn, user):
        season, group = group_for_user(conn, user["id"])
        return {
            "season": row_to_dict(season),
            "group": row_to_dict(group),
            "challenges": list_challenges(conn, season["id"], user["id"]),
            "suggested_rivals": suggested_rivals(conn, season["id"], user["id"]),
            "monthly": list_monthly_challenges(conn, season, user["id"]),
            "weekly": weekly_challenges(conn, season["id"], user["id"]),
            "notifications": list_notifications(conn, user["id"]),
        }

    def claim_monthly_challenge(self, conn, user, challenge_id):
        season = active_season(conn)
        try:
            feedback = claim_monthly_challenge(conn, season, user["id"], challenge_id)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"feedback": feedback, "monthly": list_monthly_challenges(conn, season, user["id"])}

    def create_challenge(self, conn, user):
        body = read_json(self)
        season = active_season(conn)
        try:
            if body.get("type") == "automatic":
                challenge_id = create_automatic_challenge(
                    conn,
                    season["id"],
                    user["id"],
                    int(body.get("challenged_id")),
                    int(body["challenger_partner_id"]) if body.get("challenger_partner_id") else None,
                    int(body["challenged_partner_id"]) if body.get("challenged_partner_id") else None,
                )
            else:
                challenge_id = create_open_challenge(
                    conn,
                    season["id"],
                    user["id"],
                    int(body.get("challenged_id")),
                    body.get("title"),
                    body.get("description", ""),
                    int(body["challenger_partner_id"]) if body.get("challenger_partner_id") else None,
                    int(body["challenged_partner_id"]) if body.get("challenged_partner_id") else None,
                )
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"challenge_id": challenge_id}

    def challenge_action(self, conn, user, challenge_id, action):
        body = read_json(self)
        try:
            if action == "accept":
                accept_challenge(conn, challenge_id, user["id"])
                return {"accepted": True}
            if action == "reject":
                reject_challenge(conn, challenge_id, user["id"])
                return {"rejected": True}
            if action == "submit-result":
                match_id = submit_challenge_result(
                    conn,
                    challenge_id,
                    user["id"],
                    body.get("score", ""),
                    body.get("is_walkover", False),
                )
                return {"match_id": match_id, "status": "pending_confirmation"}
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        raise ApiError(404, "Accion de reto no encontrada.")

    def create_match(self, conn, user):
        body = read_json(self)
        season, group = group_for_user(conn, user["id"])
        team_a = [user["id"], int(body.get("team_a_player_2_id"))]
        team_b = [int(body.get("team_b_player_1_id")), int(body.get("team_b_player_2_id"))]
        all_players = team_a + team_b
        if len(set(all_players)) != 4:
            raise ApiError(400, "El partido debe tener cuatro jugadores distintos.")
        for player_id in all_players:
            member = scalar(
                conn,
                "SELECT COUNT(*) FROM group_members WHERE group_id = ? AND user_id = ? AND active = 1",
                (group["id"], player_id),
            )
            if not member:
                raise ApiError(400, "Todos los jugadores deben pertenecer a tu grupo activo.")
        parsed = parse_score(body.get("score", ""))
        winner_side = parsed["winner_side"]
        loser_side = "B" if winner_side == "A" else "A"
        winners = team_a if winner_side == "A" else team_b
        losers = team_b if winner_side == "A" else team_a
        cursor = conn.execute(
            """
            INSERT INTO matches
            (season_id, group_id, player_a_id, player_b_id,
             team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id,
             created_by, status, is_walkover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_confirmation', ?)
            """,
            (
                season["id"],
                group["id"],
                team_a[0],
                team_b[0],
                team_a[0],
                team_a[1],
                team_b[0],
                team_b[1],
                user["id"],
                int(bool(body.get("is_walkover", False))),
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
                body.get("score", ""),
                first_or_none(winners),
                first_or_none(losers),
                winner_side,
                loser_side,
                parsed[winner_side.lower()]["sets_won"],
                parsed[loser_side.lower()]["sets_won"],
                parsed[winner_side.lower()]["games_won"],
                parsed[loser_side.lower()]["games_won"],
                user["id"],
            ),
        )
        return {"match_id": match_id, "status": "pending_confirmation"}

    def confirm_match(self, conn, user, match_id):
        match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not match:
            raise ApiError(404, "Partido no encontrado.")
        if user["id"] not in participant_ids(match) and user["role"] != "admin":
            raise ApiError(403, "No puedes confirmar este partido.")
        if user["role"] != "admin":
            creator_team = player_team(match, match["created_by"])
            confirmer_team = player_team(match, user["id"])
            if user["id"] == match["created_by"] or confirmer_team == creator_team:
                raise ApiError(403, "Debe confirmarlo al menos un jugador de la pareja rival.")
        before_ranking = ranking_for_group(conn, match["season_id"], match["group_id"])
        before_row = next((row for row in before_ranking if row["user_id"] == user["id"]), None)
        before_position = before_row["rank_position"] if before_row else None
        before_zone = before_row["movement_zone"] if before_row else None
        before_xp = scalar(conn, "SELECT xp_total FROM player_profiles WHERE user_id = ?", (user["id"],)) or 0
        conn.execute(
            "UPDATE matches SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (match_id,),
        )
        conn.execute("UPDATE match_results SET confirmed_by = ?, conflict_note = '' WHERE match_id = ?", (user["id"], match_id))
        apply_match_xp(conn, match_id)
        apply_rating_for_match(conn, match_id)
        complete_challenge_for_match(conn, match_id)
        after_ranking = ranking_for_group(conn, match["season_id"], match["group_id"], persist=True)
        feedback = match_feedback(conn, match_id, user["id"], before_position, before_xp, after_ranking, before_zone)
        return {"confirmed": True, "feedback": feedback}

    def conflict_match(self, conn, user, match_id):
        match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not match or user["id"] not in participant_ids(match):
            raise ApiError(404, "Partido no encontrado.")
        body = read_json(self)
        reason = body.get("reason", "El rival no esta de acuerdo con el resultado.")
        conn.execute("UPDATE matches SET status = 'conflict' WHERE id = ?", (match_id,))
        conn.execute("UPDATE match_results SET conflict_note = ? WHERE match_id = ?", (reason, match_id))
        conn.execute("INSERT INTO admin_reviews (match_id, reason) VALUES (?, ?)", (match_id, reason))
        return {"conflict": True}

    def leaderboard(self, conn, query):
        order = query.get("order", ["rating"])[0]
        allowed = {"rating": "p.rating DESC", "xp": "p.xp_total DESC", "division": "d.sort_order ASC, p.rating DESC"}
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT u.id AS user_id, p.display_name, p.rating, p.xp_total, p.xp_monthly,
                       l.city, l.region, d.name AS division_name, d.sort_order,
                       ab.image_path AS avatar_base_image, frame.name AS equipped_frame_name
                FROM users u
                JOIN player_profiles p ON p.user_id = u.id
                JOIN locations l ON l.id = p.location_id
                LEFT JOIN divisions d ON d.id = p.current_division_id
                LEFT JOIN user_avatars ua ON ua.user_id = u.id
                LEFT JOIN avatar_bases ab ON ab.id = ua.base_avatar_id
                LEFT JOIN avatar_items frame ON frame.id = ua.equipped_frame
                WHERE u.role = 'player'
                ORDER BY {allowed.get(order, allowed['rating'])}
                LIMIT 100
                """
            ).fetchall()
        )
        for index, row in enumerate(rows, start=1):
            row["rank_position"] = index
        return {"leaderboard": rows, "order": order}

    def progress(self, conn, user):
        profile = row_to_dict(profile_for_user(conn, user["id"]))
        history = rows_to_dicts(
            conn.execute(
                """
                SELECT h.*, fd.name AS from_division, td.name AS to_division
                FROM promotion_relegation_history h
                LEFT JOIN divisions fd ON fd.id = h.from_division_id
                LEFT JOIN divisions td ON td.id = h.to_division_id
                WHERE h.user_id = ?
                ORDER BY h.created_at DESC
                """,
                (user["id"],),
            ).fetchall()
        )
        rating_history = rows_to_dicts(
            conn.execute(
                "SELECT * FROM rating_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                (user["id"],),
            ).fetchall()
        )
        xp = rows_to_dicts(
            conn.execute(
                "SELECT * FROM xp_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                (user["id"],),
            ).fetchall()
        )
        return {
            "profile": profile,
            "level": xp_level(profile["xp_total"]),
            "history": history,
            "rating_history": rating_history,
            "xp": xp,
            "identity": player_identity(conn, user["id"]),
        }

    def achievements(self, conn, user):
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT a.code, a.name, a.description, ua.earned_at
                FROM achievements a
                LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.user_id = ?
                ORDER BY a.id
                """,
                (user["id"],),
            ).fetchall()
        )
        return {"achievements": rows}

    def avatar(self, conn, user):
        profile = row_to_dict(profile_for_user(conn, user["id"]))
        season, group = group_for_user(conn, user["id"])
        ranking = public_ranking_rows(ranking_for_group(conn, season["id"], group["id"], persist=True))
        ranking_entry = next((row for row in ranking if row["user_id"] == user["id"]), None)
        avatar_data = avatar_payload(conn, user["id"])
        achievements = rows_to_dicts(
            conn.execute(
                """
                SELECT a.code, a.name, a.description, ua.earned_at
                FROM achievements a
                JOIN user_achievements ua ON ua.achievement_id = a.id
                WHERE ua.user_id = ?
                ORDER BY ua.earned_at DESC
                LIMIT 4
                """,
                (user["id"],),
            ).fetchall()
        )
        return {**avatar_data, "profile": profile, "level": xp_level(profile["xp_total"]), "ranking_entry": ranking_entry, "achievements": achievements}

    def update_avatar(self, conn, user):
        body = read_json(self)
        try:
            if body.get("base_avatar_id"):
                set_avatar_base(conn, user["id"], int(body["base_avatar_id"]))
            if body.get("item_id"):
                equip_avatar_item(conn, user["id"], int(body["item_id"]))
            if body.get("unequip_category"):
                unequip_avatar_category(conn, user["id"], body["unequip_category"])
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return self.avatar(conn, user)

    def playtomic(self, conn, user):
        row = conn.execute("SELECT * FROM playtomic_connections WHERE user_id = ?", (user["id"],)).fetchone()
        return {"connection": row_to_dict(row)}

    def update_playtomic(self, conn, user):
        body = read_json(self)
        status = body.get("status", "not_connected")
        playtomic_id = body.get("playtomic_id", "")
        conn.execute(
            """
            INSERT INTO playtomic_connections (user_id, playtomic_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET playtomic_id = excluded.playtomic_id, status = excluded.status
            """,
            (user["id"], playtomic_id, status),
        )
        conn.execute("UPDATE player_profiles SET playtomic_id = ? WHERE user_id = ?", (playtomic_id, user["id"]))
        return self.playtomic(conn, user)

    def admin(self, conn, method, path, user):
        season = active_season(conn)
        if method == "GET" and path == "/api/admin/overview":
            return founder_dashboard(conn, season)
        if method == "POST" and path == "/api/admin/recalculate-rankings":
            rows = recalc_all_rankings(conn, season["id"])
            return {"recalculated": len(rows)}
        if method == "POST" and path == "/api/admin/regenerate-groups":
            updated = 0
            for division in divisions(conn):
                updated += len(rebalance_division_if_safe(conn, season["id"], division["id"]))
            return {"groups_checked": updated}
        if method == "POST" and path == "/api/admin/close-season":
            return close_monthly_season(conn, season["id"])
        if method == "POST" and path == "/api/admin/validate-pending-result":
            row = conn.execute(
                "SELECT id FROM matches WHERE season_id = ? AND status = 'pending_confirmation' ORDER BY created_at ASC LIMIT 1",
                (season["id"],),
            ).fetchone()
            if not row:
                return {"validated": False, "reason": "No hay resultados pendientes."}
            result = self.confirm_match(conn, user, row["id"])
            return {"validated": True, "match_id": row["id"], **result}
        if method == "POST" and path == "/api/admin/resolve-dispute":
            row = conn.execute(
                """
                SELECT ar.id AS review_id, ar.match_id
                FROM admin_reviews ar
                JOIN matches m ON m.id = ar.match_id
                WHERE ar.status = 'open'
                ORDER BY ar.created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return {"resolved": False, "reason": "No hay disputas abiertas."}
            result = self.confirm_match(conn, user, row["match_id"])
            conn.execute(
                "UPDATE admin_reviews SET status = 'resolved', resolved_by = ?, resolution = 'Validado desde Founder Dashboard', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user["id"], row["review_id"]),
            )
            return {"resolved": True, "review_id": row["review_id"], "match_id": row["match_id"], **result}
        raise ApiError(404, "Endpoint admin no encontrado.")


def founder_dashboard(conn, season):
    season_id = season["id"]
    conflicts = open_admin_reviews(conn)
    rankings = []
    for group in conn.execute("SELECT id FROM groups WHERE season_id = ?", (season_id,)).fetchall():
        rankings.extend(ranking_for_group(conn, season_id, group["id"]))

    metrics = {
        "registered_users": scalar(conn, "SELECT COUNT(*) FROM users WHERE role = 'player'") or 0,
        "active_today": scalar(conn, "SELECT COUNT(*) FROM player_profiles p JOIN users u ON u.id = p.user_id WHERE u.role = 'player' AND date(COALESCE(p.last_active_at, u.created_at)) = date('now')") or 0,
        "active_7d": scalar(conn, "SELECT COUNT(*) FROM player_profiles p JOIN users u ON u.id = p.user_id WHERE u.role = 'player' AND julianday(COALESCE(p.last_active_at, u.created_at)) >= julianday('now', '-7 days')") or 0,
        "matches_registered": (scalar(conn, "SELECT COUNT(*) FROM matches") or 0) + (scalar(conn, "SELECT COUNT(*) FROM free_matches") or 0),
        "official_matches": scalar(conn, "SELECT COUNT(*) FROM matches") or 0,
        "free_matches": scalar(conn, "SELECT COUNT(*) FROM free_matches") or 0,
        "pending_results": scalar(conn, "SELECT COUNT(*) FROM matches WHERE status = 'pending_confirmation'") or 0,
        "invitations_sent": scalar(conn, "SELECT COUNT(*) FROM free_match_invitations") or 0,
        "invitations_converted": scalar(conn, "SELECT COUNT(*) FROM free_match_invitations WHERE registered_user_id IS NOT NULL") or 0,
        "active_leagues": scalar(conn, "SELECT COUNT(DISTINCT division_id) FROM groups WHERE season_id = ? AND status = 'active'", (season_id,)) or 0,
        "active_groups": scalar(conn, "SELECT COUNT(*) FROM groups WHERE season_id = ? AND status = 'active'", (season_id,)) or 0,
        "beta_feedback": scalar(conn, "SELECT COUNT(*) FROM beta_feedback") or 0,
    }
    competitive = competitive_admin_state(conn, season_id, rankings)
    errors = recent_error_logs(conn)
    alerts = admin_alerts(conn, metrics, competitive, len(errors), len(conflicts), rankings)
    return {
        "metrics": metrics,
        "users": metrics["registered_users"],
        "groups": metrics["active_groups"],
        "matches_pending_review": len(conflicts),
        "season": row_to_dict(season),
        "conflicts": conflicts,
        "divisions": divisions(conn),
        "activity": admin_activity(conn, season_id),
        "competitive": competitive,
        "errors": errors,
        "beta_feedback": recent_beta_feedback(conn),
        "health": {
            "database": "OK" if scalar(conn, "SELECT 1") == 1 else "Revisar",
            "tests_passed": None,
            "last_successful_run": None,
            "version": APP_VERSION,
            "environment": APP_ENV,
        },
        "alerts": alerts,
    }


def open_admin_reviews(conn):
    return rows_to_dicts(
        conn.execute(
            """
            SELECT ar.*, r.score, pa.display_name AS player_a, pb.display_name AS player_b
            FROM admin_reviews ar
            JOIN matches m ON m.id = ar.match_id
            JOIN match_results r ON r.match_id = m.id
            JOIN player_profiles pa ON pa.user_id = m.player_a_id
            JOIN player_profiles pb ON pb.user_id = m.player_b_id
            WHERE ar.status = 'open'
            ORDER BY ar.created_at DESC
            LIMIT 12
            """
        ).fetchall()
    )


def admin_activity(conn, season_id):
    return {
        "series": activity_series(conn),
        "latest_registrations": rows_to_dicts(
            conn.execute(
                """
                SELECT u.id AS user_id, u.email, u.created_at, p.display_name, l.city
                FROM users u
                JOIN player_profiles p ON p.user_id = u.id
                JOIN locations l ON l.id = p.location_id
                WHERE u.role = 'player'
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
        "latest_matches": rows_to_dicts(
            conn.execute(
                """
                SELECT m.id, m.status, m.source, m.created_at, COALESCE(r.score, '') AS score,
                       pa.display_name AS player_a, pb.display_name AS player_b
                FROM matches m
                LEFT JOIN match_results r ON r.match_id = m.id
                JOIN player_profiles pa ON pa.user_id = m.player_a_id
                JOIN player_profiles pb ON pb.user_id = m.player_b_id
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
        "latest_confirmed_results": rows_to_dicts(
            conn.execute(
                """
                SELECT m.id, m.confirmed_at, r.score, pa.display_name AS player_a, pb.display_name AS player_b
                FROM matches m
                JOIN match_results r ON r.match_id = m.id
                JOIN player_profiles pa ON pa.user_id = m.player_a_id
                JOIN player_profiles pb ON pb.user_id = m.player_b_id
                WHERE m.status = 'confirmed'
                ORDER BY m.confirmed_at DESC, m.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
        "latest_completed_challenges": rows_to_dicts(
            conn.execute(
                """
                SELECT c.id, c.title, c.completed_at, pc.display_name AS challenger, pr.display_name AS challenged
                FROM challenges c
                JOIN player_profiles pc ON pc.user_id = c.challenger_id
                JOIN player_profiles pr ON pr.user_id = c.challenged_id
                WHERE c.status = 'completed'
                ORDER BY c.completed_at DESC, c.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
        "latest_movements": rows_to_dicts(
            conn.execute(
                """
                SELECT h.id, h.movement, h.created_at, p.display_name, fd.name AS from_division, td.name AS to_division
                FROM promotion_relegation_history h
                JOIN player_profiles p ON p.user_id = h.user_id
                LEFT JOIN divisions fd ON fd.id = h.from_division_id
                LEFT JOIN divisions td ON td.id = h.to_division_id
                ORDER BY h.created_at DESC, h.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
        "latest_invitations": rows_to_dicts(
            conn.execute(
                """
                SELECT i.id, i.created_at, i.accepted_at, ep.display_name AS external_player, p.display_name AS invited_by_name,
                       i.registered_user_id
                FROM free_match_invitations i
                JOIN external_players ep ON ep.id = i.external_player_id
                JOIN player_profiles p ON p.user_id = i.invited_by
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT 8
                """
            ).fetchall()
        ),
    }


def activity_series(conn):
    today = date.today()
    series = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_text = day.isoformat()
        users = scalar(conn, "SELECT COUNT(*) FROM users WHERE date(created_at) = ?", (day_text,)) or 0
        matches = scalar(conn, "SELECT COUNT(*) FROM matches WHERE date(created_at) = ?", (day_text,)) or 0
        free_matches = scalar(conn, "SELECT COUNT(*) FROM free_matches WHERE date(created_at) = ?", (day_text,)) or 0
        series.append({"date": day_text, "users": users, "matches": matches + free_matches})
    return series


def competitive_admin_state(conn, season_id, rankings):
    groups = rows_to_dicts(
        conn.execute(
            """
            SELECT g.id, g.name, d.name AS division_name, COUNT(gm.id) AS players
            FROM groups g
            JOIN divisions d ON d.id = g.division_id
            LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.active = 1
            WHERE g.season_id = ?
            GROUP BY g.id
            ORDER BY players ASC, g.name ASC
            """,
            (season_id,),
        ).fetchall()
    )
    without_group = rows_to_dicts(
        conn.execute(
            """
            SELECT u.id AS user_id, p.display_name, l.city
            FROM users u
            JOIN player_profiles p ON p.user_id = u.id
            JOIN locations l ON l.id = p.location_id
            LEFT JOIN group_members gm ON gm.user_id = u.id AND gm.season_id = ? AND gm.active = 1
            WHERE u.role = 'player' AND gm.id IS NULL
            ORDER BY u.created_at DESC
            LIMIT 20
            """,
            (season_id,),
        ).fetchall()
    )
    without_matches = rows_to_dicts(
        conn.execute(
            """
            SELECT u.id AS user_id, p.display_name, l.city
            FROM users u
            JOIN player_profiles p ON p.user_id = u.id
            JOIN locations l ON l.id = p.location_id
            WHERE u.role = 'player'
              AND NOT EXISTS (
                SELECT 1 FROM matches m
                WHERE u.id IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
              )
              AND NOT EXISTS (SELECT 1 FROM free_matches fm WHERE fm.user_id = u.id)
            ORDER BY u.created_at DESC
            LIMIT 20
            """
        ).fetchall()
    )
    without_avatar_complete = rows_to_dicts(
        conn.execute(
            """
            SELECT u.id AS user_id, p.display_name, l.city
            FROM users u
            JOIN player_profiles p ON p.user_id = u.id
            JOIN locations l ON l.id = p.location_id
            LEFT JOIN user_avatars ua ON ua.user_id = u.id
            WHERE u.role = 'player'
              AND (
                p.gender NOT IN ('male', 'female')
                OR p.location_id IS NULL
                OR ua.user_id IS NULL
                OR ua.equipped_hair IS NULL
                OR ua.equipped_hair_color IS NULL
                OR ua.equipped_top IS NULL
                OR ua.equipped_bottom IS NULL
                OR ua.equipped_shoes IS NULL
                OR ua.equipped_racket IS NULL
              )
            ORDER BY u.created_at DESC
            LIMIT 20
            """
        ).fetchall()
    )
    return {
        "low_player_groups": [group for group in groups if group["players"] < 10],
        "forming_groups": [group for group in groups if group["players"] < 20],
        "complete_groups": [group for group in groups if group["players"] >= 30],
        "users_without_group": without_group,
        "users_without_matches": without_matches,
        "users_without_avatar_complete": without_avatar_complete,
        "promotion_zone_users": [row for row in rankings if row["movement_zone"] == "promotion"][:20],
        "relegation_zone_users": [row for row in rankings if row["movement_zone"] == "relegation"][:20],
    }


def recent_error_logs(conn):
    return rows_to_dicts(
        conn.execute(
            """
            SELECT e.*, p.display_name
            FROM error_logs e
            LEFT JOIN player_profiles p ON p.user_id = e.user_id
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 20
            """
        ).fetchall()
    )


def recent_beta_feedback(conn):
    return rows_to_dicts(
        conn.execute(
            """
            SELECT bf.*, p.display_name
            FROM beta_feedback bf
            LEFT JOIN player_profiles p ON p.user_id = bf.user_id
            ORDER BY bf.created_at DESC
            LIMIT 12
            """
        )
    )


def admin_alerts(conn, metrics, competitive, recent_error_count, open_conflicts, rankings):
    alerts = []
    unresolved_errors = scalar(conn, "SELECT COUNT(*) FROM error_logs WHERE resolved = 0 AND julianday(created_at) >= julianday('now', '-1 day')") or 0
    old_pending = scalar(conn, "SELECT COUNT(*) FROM matches WHERE status = 'pending_confirmation' AND julianday(created_at) < julianday('now', '-2 days')") or 0
    active_without_group = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM player_profiles p
        LEFT JOIN group_members gm ON gm.user_id = p.user_id AND gm.active = 1
        WHERE p.available_for_play = 1 AND gm.id IS NULL
        """,
    ) or 0
    if unresolved_errors >= 5:
        alerts.append({"type": "danger", "title": "Muchos errores recientes", "message": f"{unresolved_errors} errores sin resolver en las ultimas 24h."})
    if old_pending:
        alerts.append({"type": "warning", "title": "Resultados pendientes antiguos", "message": f"{old_pending} resultados llevan mas de 48h pendientes."})
    if competitive["low_player_groups"]:
        alerts.append({"type": "warning", "title": "Ligas con menos de 10 jugadores", "message": f"{len(competitive['low_player_groups'])} grupos necesitan atencion."})
    if open_conflicts:
        alerts.append({"type": "danger", "title": "Conflictos abiertos", "message": f"{open_conflicts} resultados requieren revision admin."})
    if active_without_group:
        alerts.append({"type": "warning", "title": "Jugadores activos sin grupo", "message": f"{active_without_group} jugadores disponibles no tienen grupo activo."})
    if metrics["registered_users"] and metrics["active_7d"] == 0:
        alerts.append({"type": "warning", "title": "Caida de actividad", "message": "No hay jugadores activos en los ultimos 7 dias."})
    if not alerts:
        alerts.append({"type": "ok", "title": "Sistema estable", "message": "No hay alertas criticas ahora mismo."})
    return alerts


def competitive_status(row):
    if not row:
        return {"code": "middle", "label": "Zona media"}
    if row["movement_zone"] == "promotion":
        return {"code": "promotion", "label": "Zona ascenso"}
    if row["movement_zone"] == "relegation":
        return {"code": "relegation", "label": "Zona descenso"}
    return {"code": "middle", "label": "Zona media"}


def mini_ranking_around_user(ranking, user_id, radius=2):
    if not ranking:
        return []
    index = next((idx for idx, row in enumerate(ranking) if row["user_id"] == user_id), 0)
    start = max(0, index - radius)
    end = min(len(ranking), index + radius + 1)
    if end - start < radius * 2 + 1:
        start = max(0, end - (radius * 2 + 1))
        end = min(len(ranking), start + radius * 2 + 1)
    return ranking[start:end]


def next_objective(row, ranking=None):
    if not row:
        return "Juega tu primer partido competitivo."
    if row["rank_position"] <= 3:
        return "Estas en ascenso. Mantente en el top 3."
    ranking = ranking or []
    promotion_cut = next((item for item in ranking if item["rank_position"] == 3), None)
    if promotion_cut:
        needed = max(1, promotion_cut["points"] + 1 - row["points"])
        wins_needed = max(1, (needed + 2) // 3)
        if wins_needed == 1:
            return "Si ganas 1 partido entras en ascenso."
        return f"Si ganas {wins_needed} partidos entras en ascenso."
    if row["played"] < 10:
        return f"Completar {10 - row['played']} partidos validos mas."
    return "Mejorar set average para entrar en top 3."


def competitive_message(row, ranking=None):
    if not row:
        return "Juega tu primer partido competitivo para entrar en la clasificacion."
    if row["movement_zone"] == "promotion":
        return "Estas en zona de ascenso."
    if row["movement_zone"] == "relegation":
        return "Necesitas ganar para salir del descenso."
    gap = promotion_gap(row, ranking)
    return gap["label"] if gap.get("points") is not None else "Zona media. Un buen resultado te acerca al ascenso."


def match_feedback(conn, match_id, user_id, before_position=None, before_xp=0, after_ranking=None, before_zone=None):
    row = conn.execute(
        """
        SELECT
            m.id, m.season_id, m.group_id, m.player_a_id, m.player_b_id,
            m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id,
            r.winner_id, r.loser_id, r.winner_team, r.loser_team, r.score
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.id = ?
        """,
        (match_id,),
    ).fetchone()
    if not row or user_id not in participant_ids(row):
        return None
    my_team = player_team(row, user_id)
    result = "victory" if winner_team(row) == my_team else "defeat"
    after_ranking = after_ranking or ranking_for_group(conn, row["season_id"], row["group_id"], persist=True)
    after_row = next((item for item in after_ranking if item["user_id"] == user_id), None)
    after_position = after_row["rank_position"] if after_row else None
    after_zone = after_row["movement_zone"] if after_row else None
    after_xp = scalar(conn, "SELECT xp_total FROM player_profiles WHERE user_id = ?", (user_id,)) or before_xp
    rank_delta = before_position - after_position if before_position and after_position else 0
    xp_gained = max(0, after_xp - before_xp)
    points_gained = 3 if result == "victory" else 1
    entered_promotion = before_zone != "promotion" and after_zone == "promotion"
    return {
        "type": result,
        "title": "Entras en zona de ascenso" if entered_promotion else "Victoria confirmada" if result == "victory" else "Resultado confirmado",
        "message": "Estas en top 3. Ahora toca defender el ascenso." if entered_promotion else "Gran partido. Sumaste puntos, XP y presionas la zona alta." if result == "victory" else "Partido registrado. Sigues sumando ritmo y experiencia.",
        "score": row["score"],
        "points_gained": points_gained,
        "xp_gained": xp_gained,
        "before_position": before_position,
        "after_position": after_position,
        "rank_delta": rank_delta,
        "entered_promotion": entered_promotion,
        "ranking_label": ranking_feedback_label(rank_delta, after_position),
    }


def ranking_feedback_label(rank_delta, after_position):
    if rank_delta > 0:
        return f"Subes {rank_delta} puesto{'s' if rank_delta != 1 else ''}: ahora vas #{after_position}"
    if after_position:
        return f"Te mantienes en #{after_position}"
    return "Ranking actualizado"


def season_promotion_feedback(conn, user_id):
    row = conn.execute(
        """
        SELECT h.*, td.name AS to_division
        FROM promotion_relegation_history h
        JOIN divisions td ON td.id = h.to_division_id
        WHERE h.user_id = ? AND h.movement = 'promotion'
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    division = display_division_name(row["to_division"])
    return {
        "type": "promotion",
        "title": f"Has subido a {division}",
        "division": division,
        "message": "Ascenso conseguido. Nueva division, nuevos rivales y una marca mas en tu historial.",
    }


def display_division_name(name):
    return re.sub(r"(\d+)a ", r"\1ª ", name or "")


def promotion_gap(row, ranking=None):
    if not row:
        return {"points": None, "label": "Sin clasificacion"}
    if row["rank_position"] <= 3:
        return {"points": 0, "label": "Estas en zona de ascenso"}
    ranking = ranking or []
    promotion_cut = next((item for item in ranking if item["rank_position"] == 3), None)
    if not promotion_cut:
        return {"points": None, "label": "Ascenso no disponible"}
    points = max(1, promotion_cut["points"] + 1 - row["points"])
    return {
        "points": points,
        "label": f"Te faltan {points} punto{'s' if points != 1 else ''} para subir",
    }


def latest_results(conn, season_id, user_id):
    rows = conn.execute(
        """
        SELECT m.*
        FROM matches m
        JOIN match_results r ON r.match_id = m.id
        WHERE m.season_id = ? AND m.status = 'confirmed'
          AND ? IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        ORDER BY m.confirmed_at DESC, m.created_at DESC, m.id DESC
        LIMIT 10
        """,
        (season_id, user_id),
    ).fetchall()
    results = []
    for row in rows:
        payload = match_payload(conn, row, user_id)
        my_team = player_team({**dict(row), "winner_team": payload["winner_team"]}, user_id)
        won = payload["winner_team"] == my_team
        opponent = payload["team_b_label"] if my_team == "A" else payload["team_a_label"]
        results.append(
            {
                "id": row["id"],
                "opponent_name": opponent,
                "score": payload["score"],
                "source": row["source"],
                "result": "win" if won else "loss",
                "label": "Victoria" if won else "Derrota",
                "created_at": row["created_at"],
                "team_a_label": payload["team_a_label"],
                "team_b_label": payload["team_b_label"],
            }
        )
    return results


def recent_group_activity(conn, season_id, group_id, user_id):
    rows = conn.execute(
        """
        SELECT m.*
        FROM matches m
        WHERE m.season_id = ? AND m.group_id = ? AND m.status IN ('confirmed', 'pending_confirmation', 'conflict')
          AND ? NOT IN (m.player_a_id, m.player_b_id, m.team_a_player_1_id, m.team_a_player_2_id, m.team_b_player_1_id, m.team_b_player_2_id)
        ORDER BY COALESCE(m.confirmed_at, m.created_at) DESC, m.id DESC
        LIMIT 5
        """,
        (season_id, group_id, user_id),
    ).fetchall()
    activity = []
    for row in rows:
        payload = match_payload(conn, row, user_id)
        activity.append(
            {
                "id": row["id"],
                "status": payload["status"],
                "status_label": payload["status_label"],
                "team_a_label": payload["team_a_label"],
                "team_b_label": payload["team_b_label"],
                "score": payload["score"],
                "winner": payload["winner"],
                "created_at": payload["created_at"],
            }
        )
    return activity


def current_streak(results):
    if not results:
        return {"count": 0, "type": "none", "label": "Sin racha activa"}
    streak_type = results[0]["result"]
    count = 0
    for result in results:
        if result["result"] != streak_type:
            break
        count += 1
    noun = "victoria" if streak_type == "win" else "derrota"
    suffix = "seguida" if count == 1 else "seguidas"
    return {
        "count": count,
        "type": streak_type,
        "label": f"{count} {noun}{'s' if count != 1 else ''} {suffix}",
    }


def upcoming_challenges(conn, season_id, user_id):
    items = list_challenges(conn, season_id, user_id)
    return [
        item
        for item in items
        if item["type"] != "weekly" and item["status"] in ("pending", "accepted")
    ][:3]


def pending_results(conn, season_id, user_id):
    rows = conn.execute(
        """
        SELECT *
        FROM matches
        WHERE season_id = ?
          AND status = 'pending_confirmation'
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        ORDER BY created_at DESC, id DESC
        LIMIT 3
        """,
        (season_id, user_id),
    ).fetchall()
    return [match_payload(conn, row, user_id) for row in rows]


def is_new_player(conn, season_id, user_id, ranking_row=None):
    if ranking_row and ranking_row["played"] > 0:
        return False
    confirmed = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM matches
        WHERE season_id = ? AND status = 'confirmed'
          AND ? IN (player_a_id, player_b_id, team_a_player_1_id, team_a_player_2_id, team_b_player_1_id, team_b_player_2_id)
        """,
        (season_id, user_id),
    ) or 0
    return confirmed == 0


def starter_checklist(conn, season_id, user_id, profile):
    profile_done = bool(profile.get("display_name") and profile.get("city") and profile.get("club") and profile.get("level_guess") and profile.get("gender") in ("male", "female"))
    avatar_done = bool(profile.get("avatar_base_id"))
    available = bool(profile.get("available_for_play"))
    searching = bool(
        scalar(conn, "SELECT COUNT(*) FROM match_requests WHERE season_id = ? AND owner_id = ? AND status = 'open'", (season_id, user_id))
        or scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM challenges
            WHERE season_id = ? AND status IN ('pending', 'accepted')
              AND ? IN (challenger_id, challenged_id, challenger_partner_id, challenged_partner_id)
            """,
            (season_id, user_id),
        )
    )
    first_confirmed = not is_new_player(conn, season_id, user_id)
    return [
        {"key": "profile", "label": "Completar perfil", "done": profile_done},
        {"key": "avatar", "label": "Elegir avatar", "done": avatar_done},
        {"key": "availability", "label": "Marcar disponibilidad", "done": available},
        {"key": "find_match", "label": "Buscar primer partido", "done": searching or first_confirmed},
        {"key": "first_result", "label": "Confirmar primer resultado", "done": first_confirmed},
    ]


def starter_mission(conn, season_id, user_id, profile):
    completed = all(item["done"] for item in starter_checklist(conn, season_id, user_id, profile)[:3])
    claimed = bool(profile.get("initial_mission_claimed_at"))
    return {
        "title": "Completa tu perfil",
        "description": "Deja listo tu perfil, avatar y disponibilidad para poder encontrar partido rapido.",
        "reward_xp": 100,
        "status": "claimed" if claimed else "completed" if completed else "pending",
        "progress": sum(1 for item in starter_checklist(conn, season_id, user_id, profile)[:3] if item["done"]),
        "target": 3,
    }


def claim_initial_mission(conn, season_id, user_id):
    profile = row_to_dict(profile_for_user(conn, user_id))
    mission = starter_mission(conn, season_id, user_id, profile)
    if mission["status"] == "claimed":
        raise ValueError("Esta mision ya esta reclamada.")
    if mission["status"] != "completed":
        raise ValueError("Completa tu perfil antes de reclamar la recompensa.")
    grant_xp(conn, user_id, season_id, mission["reward_xp"], "onboarding", "Completa tu perfil")
    grant_achievement(conn, user_id, "profile_complete", season_id)
    conn.execute("UPDATE player_profiles SET initial_mission_claimed_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    return {
        "feedback": {
            "type": "challenge_reward",
            "title": "Primera mision completada",
            "message": "Tu perfil ya esta listo para competir en PlayUp Padel.",
            "xp_gained": mission["reward_xp"],
            "reward_item": "Perfil competitivo",
            "achievement": "Perfil listo",
        },
        "starter_mission": starter_mission(conn, season_id, user_id, row_to_dict(profile_for_user(conn, user_id))),
    }


def run(port=None, host=None):
    with connect() as conn:
        init_data(conn)
    port = int(port or APP_PORT)
    host = host or APP_HOST
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"PlayUp Padel running on http://{host}:{port} ({APP_ENV})")
    server.serve_forever()


if __name__ == "__main__":
    run()
