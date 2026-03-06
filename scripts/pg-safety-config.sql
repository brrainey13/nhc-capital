-- Postgres safety configuration for Mac mini
-- Prevents runaway queries from eating all CPU/memory
--
-- Apply with: psql -h localhost -U connorrainey -d postgres -f scripts/pg-safety-config.sql

-- Kill any query running longer than 30 minutes (was unlimited)
ALTER SYSTEM SET statement_timeout = '30min';

-- Kill idle-in-transaction connections after 10 minutes
ALTER SYSTEM SET idle_in_transaction_session_timeout = '10min';

-- Limit parallel workers so a single query can't eat all cores
-- M4 has 10 cores; cap at 2 workers per query, 4 total
ALTER SYSTEM SET max_parallel_workers_per_gather = 2;
ALTER SYSTEM SET max_parallel_workers = 4;

-- Log slow queries (> 5 seconds) so we can optimize them
ALTER SYSTEM SET log_min_duration_statement = 5000;

-- Apply
SELECT pg_reload_conf();

-- Verify
SHOW statement_timeout;
SHOW idle_in_transaction_session_timeout;
SHOW max_parallel_workers_per_gather;
SHOW max_parallel_workers;
SHOW log_min_duration_statement;
