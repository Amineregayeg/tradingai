"""Integration test conftest.

Integration tests use the standard `client` fixture from the root conftest.py,
which wires an in-memory SQLite engine.  PostgreSQL-specific types (JSONB,
custom ENUMs) cannot be created in SQLite, so the `engine` fixture in the root
conftest uses `checkfirst=True` — tables whose DDL cannot be compiled are
silently skipped.

If a test in this directory requires tables with JSONB columns (e.g. alerts,
audit_log), those tables will NOT exist in the SQLite test DB and the test must
either be run against a real PostgreSQL instance or be written to avoid DDL
limitations.

All tests here are marked @pytest.mark.integration automatically via the
`pytestmark` in each test module, but they run against the shared in-memory
SQLite `client` fixture unless DATABASE_URL is overridden to a PostgreSQL URL
in the environment.
"""
