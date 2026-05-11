import base64
import hashlib
import hmac
import os
import time


SECRET = os.environ.get("PLAYUP_SECRET", "playup-local-dev-secret")


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password, stored):
    try:
        salt_text, digest_text = stored.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_token(user_id, ttl_seconds=60 * 60 * 24 * 14):
    expires = int(time.time()) + ttl_seconds
    payload = f"{user_id}:{expires}"
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(token.encode()).decode()


def verify_token(token):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, expires_text, signature = raw.split(":", 2)
        payload = f"{user_id}:{expires_text}"
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires_text) < int(time.time()):
            return None
        return int(user_id)
    except Exception:
        return None
