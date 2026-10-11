"""Small, single-process viewer authentication with in-memory sessions."""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


COOKIE_NAME = "rv_web_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 256
HASH_PREFIX = "scrypt"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, maxmem=128 * 1024 * 1024
    )
    return f"{HASH_PREFIX}${salt.hex()}${digest.hex()}"


def validate_password_hash(encoded: Any) -> str:
    if not isinstance(encoded, str):
        raise ValueError("password_hash must be a generated scrypt hash")
    parts = encoded.split("$")
    if len(parts) != 3 or parts[0] != HASH_PREFIX:
        raise ValueError("password_hash must be a generated scrypt hash")
    try:
        salt, digest = bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    except ValueError as exc:
        raise ValueError("password_hash contains invalid hexadecimal data") from exc
    if len(salt) != 16 or len(digest) != 64:
        raise ValueError("password_hash has invalid salt or digest length")
    if encoded != f"{HASH_PREFIX}${salt.hex()}${digest.hex()}":
        raise ValueError("password_hash must use canonical lowercase hexadecimal data")
    return encoded


def verify_password(password: str, encoded: str) -> bool:
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), encoded)


@dataclass(frozen=True)
class Session:
    username: str
    expires: float


class Auth:
    def __init__(self, config: Any, directory: Path) -> None:
        if config is None:
            config = {}
        if not isinstance(config, dict) or set(config) - {
            "enabled", "credentials_file", "origins", "secure_cookie"
        }:
            raise ValueError("auth: expected enabled, credentials_file, origins, secure_cookie")
        self.enabled = config.get("enabled", True)
        self.secure_cookie = config.get("secure_cookie", True)
        if not isinstance(self.enabled, bool) or not isinstance(self.secure_cookie, bool):
            raise ValueError("auth.enabled and auth.secure_cookie must be booleans")
        self.users: dict[str, str] = {}
        self.origins: set[str] = set()
        self.sessions: dict[str, Session] = {}
        self.attempts: dict[str, list[float]] = {}
        if not self.enabled:
            return
        origins = config.get("origins")
        if not isinstance(origins, list) or not origins:
            raise ValueError("auth.origins must list the browser origins allowed to log in")
        for origin in origins:
            if not isinstance(origin, str):
                raise ValueError("auth.origins must contain absolute HTTP(S) origins")
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.path or parsed.query or parsed.fragment or parsed.username
                or parsed.password or origin != f"{parsed.scheme}://{parsed.netloc}"
            ):
                raise ValueError("auth.origins must contain origins without paths or credentials")
            if not self.secure_cookie and (
                parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("auth.secure_cookie: false is permitted only for HTTP loopback origins")
            if self.secure_cookie and parsed.scheme != "https":
                raise ValueError("auth.secure_cookie: true requires HTTPS origins")
            self.origins.add(origin)
        credentials = config.get("credentials_file", "auth-users.yaml")
        if not isinstance(credentials, str) or not credentials:
            raise ValueError("auth.credentials_file must be a path")
        data = yaml.safe_load((directory / credentials).read_text())
        if not isinstance(data, dict) or set(data) != {"users"}:
            raise ValueError("credentials file must contain only users")
        users = data["users"]
        if not isinstance(users, list) or not 1 <= len(users) <= 3:
            raise ValueError("credentials file must contain one to three users")
        for user in users:
            if not isinstance(user, dict) or set(user) != {"username", "password_hash"}:
                raise ValueError("each user requires username and password_hash")
            username = user["username"]
            if (
                not isinstance(username, str) or not username.strip() or len(username) > 64
                or username != username.strip() or username in self.users
            ):
                raise ValueError("usernames must be unique non-empty strings of at most 64 characters")
            self.users[username] = validate_password_hash(user["password_hash"])
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    def allow_attempt(self, address: str) -> bool:
        now = time.monotonic()
        self.attempts = {
            key: [stamp for stamp in stamps if stamp > now - 60]
            for key, stamps in self.attempts.items() if any(stamp > now - 60 for stamp in stamps)
        }
        global_attempts = self.attempts.setdefault("*", [])
        local_attempts = self.attempts.setdefault(address, [])
        if len(global_attempts) >= 30 or len(local_attempts) >= 5:
            return False
        global_attempts.append(now)
        local_attempts.append(now)
        return True

    def authenticate(self, username: str, password: str) -> bool:
        encoded = self.users.get(username, self.dummy_hash)
        valid = verify_password(password, encoded)
        return valid and username in self.users

    def prune(self) -> None:
        now = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}

    def session(self, token: str | None) -> Session | None:
        if token is None:
            return None
        session = self.sessions.get(token)
        if session and session.expires > time.monotonic():
            return session
        self.sessions.pop(token, None)
        return None

    def create_session(self, username: str) -> str:
        self.prune()
        if len(self.sessions) >= MAX_SESSIONS:
            self.sessions.pop(next(iter(self.sessions)))
        token = secrets.token_urlsafe(32)
        self.sessions[token] = Session(username, time.monotonic() + SESSION_SECONDS)
        return token

    def revoke(self, token: str | None) -> None:
        if token:
            self.sessions.pop(token, None)
