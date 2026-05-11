#!/usr/bin/env python3
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_API_BASE_URL = "https://playup-padel-ob3c.onrender.com"


def request(base_url, path, method="GET", token=None, payload=None, timeout=45):
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body or "{}")


def wait_for_render(base_url, attempts=5):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            status, payload = request(base_url, "/api/status", timeout=60)
            if status == 200 and payload.get("status") == "ok":
                return payload
        except Exception as exc:
            last_error = exc
        time.sleep(min(3 * attempt, 12))
    raise RuntimeError(f"Backend no disponible tras {attempts} intentos: {last_error}")


def main():
    parser = argparse.ArgumentParser(description="Verify PlayUp Padel production API.")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="demo123")
    parser.add_argument("--write", action="store_true", help="Create a temporary beta user, feedback and free match.")
    args = parser.parse_args()

    base_url = args.api_base_url.rstrip("/")
    print(f"Checking {base_url}")
    print("status", wait_for_render(base_url))

    token = None
    if args.email:
        _, login = request(base_url, "/api/auth/login", "POST", payload={"email": args.email, "password": args.password})
        token = login["token"]
        print("login ok")
    elif args.write:
        suffix = int(time.time())
        email = f"beta.verify.{suffix}@playup.test"
        _, registered = request(
            base_url,
            "/api/auth/register",
            "POST",
            payload={
                "display_name": f"Beta Verify {suffix}",
                "email": email,
                "password": args.password,
                "gender": "male",
                "level_guess": "Intermedio",
                "city": "Madrid",
                "availability_text": "Tardes",
                "available_for_play": "on",
            },
        )
        token = registered["token"]
        print(f"registro/onboarding ok: {email}")
    else:
        raise SystemExit("Provide --email for login verification or --write to create a temporary beta user.")

    checks = [
        ("bootstrap", "/api/bootstrap"),
        ("home", "/api/home"),
        ("ranking", "/api/leaderboard?order=rating"),
        ("partidos/free matches", "/api/matches"),
        ("avatar", "/api/avatar"),
        ("retos", "/api/challenges"),
        ("compartir", "/api/share-card?type=status&format=story"),
    ]
    for label, path in checks:
        status, payload = request(base_url, path, token=token)
        print(label, "ok", status, sorted(payload.keys())[:6])

    if args.write:
        _, feedback = request(
            base_url,
            "/api/feedback",
            "POST",
            token=token,
            payload={"type": "feedback", "rating": 5, "message": "Verificación automática beta producción.", "url": base_url},
        )
        print("feedback ok", feedback.get("received"))
        _, free_match = request(
            base_url,
            "/api/free-matches",
            "POST",
            token=token,
            payload={
                "partner_external_name": "Smoke Partner",
                "rival_1_external_name": "Smoke Rival 1",
                "rival_2_external_name": "Smoke Rival 2",
                "club_name": "Smoke Test",
                "played_on": "2026-05-11",
                "score": "6-4 6-4",
            },
        )
        print("free match write ok", sorted(free_match.keys()))

    print("Production API verification complete.")


if __name__ == "__main__":
    main()
