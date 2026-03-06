"""Regression tests for dashboard auth middleware."""

import os
from unittest.mock import AsyncMock, patch

from routes import tables


def _mock_tables():
    pool = AsyncMock()
    pool.fetchval.return_value = 12
    return (
        patch.object(tables, "ALLOWED_TABLES", {"teams"}),
        patch.object(tables, "TABLE_DB_MAP", {"teams": "nhl_betting"}),
        patch.object(tables, "pools", {"nhl_betting": pool}),
    )


class TestAuthMiddleware:
    def test_allowed_emails_are_read_at_request_time(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools:
            with fastapi_client(base_url="http://dashboard.test") as client:
                with patch.dict(os.environ, {"ALLOWED_EMAILS": "wrong@example.com"}, clear=False):
                    denied = client.get(
                        "/api/tables",
                        headers={"cf-access-authenticated-user-email": "test@example.com"},
                    )
                with patch.dict(os.environ, {"ALLOWED_EMAILS": "test@example.com"}, clear=False):
                    allowed = client.get(
                        "/api/tables",
                        headers={"cf-access-authenticated-user-email": "test@example.com"},
                    )

        assert denied.status_code == 403, "Middleware should deny emails not present in the current env value."
        assert allowed.status_code == 200, "Middleware should re-read ALLOWED_EMAILS for each request."

    def test_valid_cloudflare_email_gets_200(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get(
                "/api/tables",
                headers={"cf-access-authenticated-user-email": "test@example.com"},
            )

        assert response.status_code == 200, "Authorized Cloudflare users should reach protected API routes."

    def test_invalid_email_gets_403(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get(
                "/api/tables",
                headers={"cf-access-authenticated-user-email": "blocked@example.com"},
            )

        assert response.status_code == 403, "Unauthorized Cloudflare emails should be rejected with 403."

    def test_missing_allowed_emails_denies_all_cloudflare_users(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://dashboard.test") as client, patch.dict(
            os.environ,
            {"DASHBOARD_API_KEY": "super-secret-test-key"},
            clear=True,
        ):
            response = client.get(
                "/api/tables",
                headers={"cf-access-authenticated-user-email": "test@example.com"},
            )

        assert response.status_code == 403, "An empty ALLOWED_EMAILS env var should deny all Cloudflare identities."

    def test_valid_api_key_gets_through(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get("/api/tables", headers={"x-api-key": "super-secret-test-key"})

        assert response.status_code == 200, "Requests with the configured API key should pass auth."

    def test_invalid_api_key_gets_403(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get("/api/tables", headers={"x-api-key": "bad-key"})

        assert response.status_code == 403, "Requests with the wrong API key should be rejected with 403."

    def test_localhost_requests_pass_without_auth(self, fastapi_client):
        allowed_tables, table_map, pools = _mock_tables()
        with allowed_tables, table_map, pools, fastapi_client(base_url="http://localhost") as client:
            response = client.get("/api/tables")

        assert response.status_code == 200, "Localhost API requests should bypass auth for local development."

    def test_health_endpoint_is_always_accessible(self, fastapi_client):
        with fastapi_client(base_url="http://dashboard.test") as client:
            response = client.get("/api/health")

        assert response.status_code == 200, "The health endpoint should remain public."
        assert response.json() == {"status": "ok"}, "The health endpoint should return the standard ok payload."
