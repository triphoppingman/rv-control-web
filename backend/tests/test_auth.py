"""Authentication coverage for HTTP, WebSocket, sessions, and configuration."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.auth import Auth, COOKIE_NAME, SESSION_SECONDS, Session, hash_password, verify_password

os.environ.setdefault("RV_WEB_CONFIG", str(Path(__file__).resolve().parents[2] / "config.test.yaml"))
from backend.app import main


ORIGIN = "http://127.0.0.1:8000"
PASSWORD = "a long test-only password"


async def no_mqtt() -> None:
    return


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.password_hash = hash_password(PASSWORD)

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.credentials = self.root / "users.yaml"
        self.credentials.write_text(yaml.safe_dump({
            "users": [{"username": "viewer", "password_hash": self.password_hash}],
        }))
        self.config = {
            "credentials_file": "users.yaml", "origins": [ORIGIN], "secure_cookie": False,
        }
        self.auth = Auth(self.config, self.root)
        self.auth_patch = patch.object(main, "auth", self.auth)
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.client = TestClient(main.app, base_url=ORIGIN)

    def login(self, client: TestClient | None = None):
        return (client or self.client).post(
            "/api/auth/login", headers={"Origin": ORIGIN},
            json={"username": "viewer", "password": PASSWORD},
        )

    def test_password_hashes_are_salted_and_verified(self) -> None:
        self.assertTrue(verify_password(PASSWORD, self.password_hash))
        self.assertFalse(verify_password("wrong", self.password_hash))
        self.assertNotEqual(hash_password(PASSWORD), self.password_hash)

    def test_protected_http_surfaces_require_session(self) -> None:
        for path in ["/api/config", "/healthz", "/assets/private.png"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertFalse(self.client.get("/api/auth/session").json()["authenticated"])
        self.assertNotEqual(self.client.get("/").status_code, 401)

    def test_built_login_assets_are_public_and_separate_from_widget_assets(self) -> None:
        assets = list(main.DIST.glob("ui-assets/*.js"))
        if not assets:
            self.skipTest("Requires a frontend build")
        response = self.client.get(f"/ui-assets/{assets[0].name}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/assets/private.png").status_code, 401)

    def test_login_cookie_and_dashboard_access(self) -> None:
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn(f"Max-Age={SESSION_SECONDS}", cookie)
        self.assertNotIn("Secure;", cookie)
        self.assertEqual(self.client.get("/api/config").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/session").json()["username"], "viewer")
        self.assertNotIn("password_hash", self.client.get("/api/config").text)

    def test_invalid_password_and_unknown_user_share_generic_error(self) -> None:
        responses = [
            self.client.post("/api/auth/login", headers={"Origin": ORIGIN},
                             json={"username": name, "password": "wrong"})
            for name in ["viewer", "unknown"]
        ]
        self.assertEqual(responses[0].status_code, 401)
        self.assertEqual(responses[0].json(), responses[1].json())

    def test_invalid_login_input_does_not_echo_password(self) -> None:
        password = "do-not-echo-this-" * 100
        response = self.client.post("/api/auth/login", headers={"Origin": ORIGIN},
                                   json={"username": "viewer", "password": password})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("do-not-echo-this", response.text)

    def test_login_and_logout_reject_untrusted_or_missing_origin(self) -> None:
        self.login()
        for origin in [None, "https://evil.example"]:
            headers = {"Origin": origin} if origin else {}
            self.assertEqual(self.client.post("/api/auth/login", headers=headers,
                json={"username": "viewer", "password": PASSWORD}).status_code, 403)
            self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/config").status_code, 200)

    def test_logout_revokes_cookie_and_previous_token(self) -> None:
        self.login()
        old = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code, 204)
        self.assertIsNone(self.auth.session(old))
        self.assertEqual(self.client.get("/api/config").status_code, 401)

    def test_expired_sessions_cannot_access_http(self) -> None:
        self.login()
        token = self.client.cookies.get(COOKIE_NAME)
        self.auth.sessions[token] = Session("viewer", time.monotonic() - 1)
        self.assertEqual(self.client.get("/api/config").status_code, 401)

    def test_login_rotation_revokes_existing_session(self) -> None:
        self.login()
        old = self.client.cookies.get(COOKIE_NAME)
        self.login()
        self.assertIsNone(self.auth.session(old))
        self.assertNotEqual(old, self.client.cookies.get(COOKIE_NAME))

    def test_rate_limit_blocks_before_password_work(self) -> None:
        for _ in range(5):
            self.assertTrue(self.auth.allow_attempt("test-address"))
        self.assertFalse(self.auth.allow_attempt("test-address"))
        for index in range(25):
            self.assertTrue(self.auth.allow_attempt(f"other-{index}"))
        self.assertFalse(self.auth.allow_attempt("new-address"))
        self.auth.attempts.clear()
        for _ in range(5):
            self.login()
        with patch.object(self.auth, "authenticate") as authenticate:
            response = self.login()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["retry-after"], "60")
            authenticate.assert_not_called()

    def test_websocket_rejects_missing_session_and_wrong_origin(self) -> None:
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": ORIGIN}):
                pass
        self.login()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": "https://evil.example"}):
                pass

    def test_websocket_delivers_snapshot_and_closes_on_logout(self) -> None:
        with patch.object(main, "receive_mqtt", no_mqtt), TestClient(main.app, base_url=ORIGIN) as client:
            self.login(client)
            with client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": ORIGIN}) as socket:
                socket.send_json({"type": "subscribe", "tab": "power"})
                self.assertEqual(socket.receive_json()["type"], "snapshot")
                client.post("/api/auth/logout", headers={"Origin": ORIGIN})
                with self.assertRaises(WebSocketDisconnect) as error:
                    socket.receive_json()
                self.assertEqual(error.exception.code, 4401)

    def test_idle_websocket_closes_after_expiry_without_telemetry(self) -> None:
        with patch.object(main, "receive_mqtt", no_mqtt), TestClient(main.app, base_url=ORIGIN) as client:
            self.login(client)
            with client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": ORIGIN}) as socket:
                token = client.cookies.get(COOKIE_NAME)
                self.auth.sessions[token] = Session("viewer", time.monotonic() - 1)
                with self.assertRaises(WebSocketDisconnect) as error:
                    socket.receive_json()
                self.assertEqual(error.exception.code, 4401)
        self.assertEqual(self.auth.sessions, {})

    def test_config_fails_closed_and_limits_credentials(self) -> None:
        for config in [{}, {**self.config, "origins": []},
                       {**self.config, "origins": ["http://example.com"]},
                       {**self.config, "secure_cookie": True},
                       {**self.config, "credentials_file": "missing.yaml"}]:
            with self.subTest(config=config), self.assertRaises((ValueError, OSError)):
                Auth(config, self.root)
        self.credentials.write_text(yaml.safe_dump({
            "users": [{"username": f"user{index}", "password_hash": self.password_hash}
                      for index in range(4)],
        }))
        with self.assertRaisesRegex(ValueError, "one to three"):
            Auth(self.config, self.root)

    def test_secure_cookie_for_https(self) -> None:
        secure = Auth({**self.config, "origins": ["https://rv.example.com"], "secure_cookie": True}, self.root)
        with patch.object(main, "auth", secure):
            client = TestClient(main.app, base_url="https://rv.example.com")
            response = client.post("/api/auth/login", headers={"Origin": "https://rv.example.com"},
                                   json={"username": "viewer", "password": PASSWORD})
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertEqual(client.get("/api/config").status_code, 200)

    def test_explicit_disabled_test_mode_preserves_dashboard(self) -> None:
        with patch.object(main, "auth", Auth({"enabled": False}, self.root)):
            self.assertEqual(self.client.get("/api/config").status_code, 200)
            self.assertFalse(self.client.get("/api/auth/session").json()["enabled"])


if __name__ == "__main__":
    unittest.main()
