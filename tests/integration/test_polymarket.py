"""Integration tests for Polymarket data on Pi."""

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def pi_db():
    """Try to connect to clawd DB on Pi (via Tailscale)."""
    pi_host = os.environ.get("PI_DB_HOST")
    if not pi_host:
        pytest.skip("PI_DB_HOST env var not set")
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=pi_host,
            port=5432,
            user="postgres",
            dbname="clawd",
            connect_timeout=5,
        )
        yield conn
        conn.close()
    except Exception:
        pytest.skip("Pi database not reachable")


class TestPolymarketConnection:
    def test_can_connect(self, pi_db):
        with pi_db.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1

    def test_markets_table_exists(self, pi_db):
        with pi_db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'markets'"
            )
            assert cur.fetchone()[0] > 0

    def test_recent_snapshots(self, pi_db):
        """Check for data from last 7 days."""
        with pi_db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM market_snapshots "
                "WHERE snapshot_time > NOW() - INTERVAL '7 days'"
            )
            count = cur.fetchone()[0]
            assert count > 0, "No recent market snapshots found"
